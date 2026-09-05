# localdb

Connect to tables you already downloaded. A folder of data files — CSV,
TSV, Excel, JSON, Parquet, zip archives — or a SQLite file is a set of
tables you can open by name, join with SQL, and link on identifiers.
No connections, no servers: the files are the tables.

## What it does

| Capability | API |
|---|---|
| Read any single file (format by extension) | `read(path, **kwargs)` |
| Treat a folder (or sqlite file) as a table set | `tables(path)` → `.names()` / `.get()` |
| SQL across files | `.query(sql)` — duckdb for folders, stdlib sqlite3 for `.sqlite` |
| Exact linking on identifiers | `ts.link(a, b, left_on=..., key_type=...)` |
| Fuzzy linking for corrupted keys | `fuzzy_link_tables(a, b, on=[...], block_on=[...])` |
| Pre-model feature audit | `audit_features(df, target=, holdout_mask=...)` → report |
| Key standardization | `standardize(df, col, kind=...)` + `register_kind()` |
| Custom file formats | `register_reader(ext, fn)` |
| Declare datasets once | `load_catalog("catalog.yaml")` / `tables_from_catalog(...)` |

Dependencies: pandas + pyyaml. Everything else is optional extras.

## Install

```bash
pip install -e ".[dev]"        # core + test tools
pip install -e ".[parquet]"    # pyarrow, for parquet files
pip install -e ".[excel]"      # openpyxl, for .xlsx
pip install -e ".[sql]"        # duckdb, for SQL across folder files
pip install -e ".[fuzzy]"      # rapidfuzz, ~10x faster fuzzy scoring
```

Without extras: csv/tsv/json/zip reading, sqlite querying, linking, fuzzy
linking all work. duckdb is only needed for SQL joins across folder files.

## Reading tables

```python
import localdb

df = localdb.read("data/clients.csv")            # one file, format by extension
df = localdb.read("data/export.zip")             # single-member zips read directly
df = localdb.read("data/warehouse.sqlite", table="clients")

ts = localdb.tables("data/downloads/")           # a folder is the table set
ts.names()                                       # tables by file stem
df = ts.get("clients", dtype={"client_id": "string"})   # kwargs reach pandas
df = ts.get("companies", columns=["CompanyNumber", "PostCode"])  # pruned read
df = ts.query("SELECT * FROM clients JOIN refs USING (id)")  # needs localdb[sql]

ts = localdb.tables("data/warehouse.sqlite")     # sqlite works the same way
```

`columns=` prunes the read where the format supports pushdown (parquet
`columns=`, csv/tsv/excel/zip `usecols=`, sqlite `SELECT col`); json and
custom readers read whole and filter. Zip members with csv/tsv content
join via SQL too: a single-tabular-member zip becomes the zip's stem view,
a multi-member zip gets one view per member (`<stem>__<member>`). The
first query on a zip converts its members to parquet in a local cache
(`$LOCALDB_CACHE_DIR`, size-capped with LRU eviction; `Tables(path,
cache=False)` to disable) — later queries scan that instead of
re-extracting and re-parsing the zip every time.

Ambiguous stems (`clients.csv` + `clients.parquet`) raise rather than guess;
a `.sqlite` file inside a folder is its own `Tables`, not a table. Ugly
stems can be aliased — `localdb.tables("data/", aliases={"companies":
"BasicCompanyData-2026-09-01-part1_7"})` — and both `get()` and `query()`
accept either name (real files win on collision; a missing alias target is
skipped with a warning).

Padded headers (Companies House files ship ` CompanyNumber`-style columns)
can be stripped: `read(..., clean_headers=True)` or
`Tables(path, clean_headers=True)` cleans column names on `get()` and in
`query()` views (per-call `clean_headers=` wins; `columns=` keeps matching
the file's raw header — cleaned names come back). Headers that collide
once stripped raise on read, and skip that view with a warning in queries.

## Catalogs

```yaml
# catalog.yaml
clients: data/clients.csv
fsa_lookup: ${DOWNLOAD_DIR}/fsa_lookup.parquet
```

```python
tables = localdb.load_catalog("catalog.yaml")
df = localdb.read(tables["fsa_lookup"])
```

When the catalog's file entries share one parent folder, open them as a
single table set aliased by entry name (the flat format doubles as the
alias map; sqlite entries are excluded — they are their own Tables):

```python
ts = localdb.tables_from_catalog("catalog.yaml")
df = ts.get("clients")                                        # alias, not the stem
df = ts.query("SELECT * FROM clients JOIN fsa_lookup USING (id)")
```

## Linking tables on identifiers

Standardize keys (format messiness removed), report quality, join, and get
a match report:

```python
result = ts.link("clients", "fsa_lookup",
                 left_on="postal_code", right_on="fsa",
                 left_key_type="fsa", right_key_type="fsa")

result.joined               # the merged DataFrame
result.match_rate_left      # share of left keys found on the right
result.unmatched_left       # sample of keys with no partner
result.duplicates           # per-side duplicate key counts (reported, not fatal)
result.nulls                # per-side null key counts
```

Shipped key cleaners: `postal_code` (case/spaces/ZIP+4), `fsa` (extracts
the FSA from a postal code), `uk_postcode` (canonical `EC1A 1BB`),
`cep` (Brazilian `12345-678`), `plz` (DE/CH/AT digits), `client_id`,
`phone` (international digits, NANP country-code strip), `email`. Register
your own:

```python
localdb.register_kind("ean13_valid", my_check_digit_validator)
```

Read id columns with `dtype=...` — integer inference silently strips leading
zeros from ids like `0600001410008`.

## Fuzzy linking

When keys are too corrupted for exact matching (typos, transposed digits),
score candidate pairs on similarity:

```python
from localdb import fuzzy_link_tables

result = fuzzy_link_tables(
    customers, customers_v2,
    on=["postcode", "given_name", "surname", "date_of_birth"],
    block_on=["postcode", "surname"],      # candidates share ANY block value
    weights={"given_name": 2.0, "surname": 2.0},
    threshold=0.75,
)

result.best_matches()      # highest-scoring partner per left row
result.matched             # all pairs >= threshold with scores
```

Similarity is normalized-indel (exact = 1.0): stdlib `difflib` by default,
or `rapidfuzz` when installed (`localdb[fuzzy]`) — same metric, roughly
10x faster. Missing fields are excluded from a pair's score. Always pass
`block_on` — without it every left/right combination is a candidate.

## Feature audit (pre-model)

Flag features before they go into a model: dead columns, target
look-alikes, temporal and train/holdout leakage. Report, not auto-drop:

```python
from localdb.feature_flags import audit_features

report = audit_features(
    df,
    target="churned",
    time_column="signup_date",
    available_as_of={"credit_score": "credit_score_pulled_at"},
    holdout_mask=df["signup_date"] >= "2026-06-01",
)

report.summary()           # one row per flagged feature, reasons collapsed
report.flagged_features()  # just the names
report.save("reports/feature_flags.csv")
```

`audit_features(df)` alone runs the non-predictive checks (constant /
near-zero variance, exact duplicate columns); `target=` unlocks target
correlation (Pearson for numeric pairs, normalized MI for categorical),
`time_column=`/`available_as_of=` unlocks temporal leakage, `holdout_mask=`
unlocks adversarial validation. Every flag carries a score and a reason.
Column names are never hardcoded — checks sort numeric vs categorical by
dtype and run on whatever the frame has. Adversarial validation scores
numeric features with XGBoost gain importances; categorical features are
never encoded into the model (encoded importances mislead for
high-cardinality columns) and are instead scored directly against the
train/holdout split with a bias-corrected Cramér's V. `scikit-learn`,
`scipy`, and `xgboost` are optional: the matching branch simply returns no
flags when its dependency is absent. Thresholds are keyword args with
defaults.

## Validated on real data

- Licence/registration extracts (csv + xlsx): links with known ground truth
  (left coverage 1.000 on licence numbers; 0.988 postal→FSA resolution)
- Companies House zips: 850k rows in 2.9s targeted; 5.69M-row scan of a
  2.8GB zip in 18.2s via `chunksize=` passthrough
- FEBRL4 record-linkage benchmark: fuzzy linking recall 0.81 / precision
  0.95 against 5000 known pairs, vs a 0.51 exact-link ceiling — locked in
  as a regression test
- Chinook sqlite: multi-table SQL, one-to-many links, cleaners on real
  international phone/email data
- Feature audit smoke on the licence + chinook extracts: flags exactly the
  genuinely constant/provenance columns, no false positives

## Known limits

- Rows still load whole — `columns=` prunes width (pushdown for parquet,
  csv, sqlite), `chunksize=` remains the row-streaming workaround
- Zip SQL queries keep a parquet copy of each zip's members in a local
  cache (first query pays the conversion — 850k-row Companies House zip:
  3.0s build, then ~0.02s/query vs 1.8s uncached; cap 10 GB via
  `LOCALDB_CACHE_MAX_GB`, `Tables(path, cache=False)` opts out). Zips
  whose CSV duckdb cannot convert are marked after one failed attempt and
  skipped on later queries (delete the `<key>.failed` marker or pass
  `cache=False` to retry)
- Postal cleaners are per-country, chosen by kind (`postal_code`, `fsa`,
  `uk_postcode`, `cep`, `plz`) — there is no country auto-detection
- Fuzzy scoring on stdlib difflib suits ~100k candidate pairs with
  `block_on`; the rapidfuzz extra is ~10x faster (FEBRL scored in 0.3s)
  and pushes that ceiling out well past a million

## Development

```bash
.venv/Scripts/python -m pytest       # Windows venv; plain `pytest` elsewhere
.venv/Scripts/python -m ruff check src tests
.venv/Scripts/python -m pytest --cov # with coverage, needs localdb[dev] (pytest-cov)
```
