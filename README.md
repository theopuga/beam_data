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
| Key standardization | `standardize(df, col, kind=...)` + `register_kind()` |
| Custom file formats | `register_reader(ext, fn)` |
| Declare datasets once | `load_catalog("catalog.yaml")` |

Dependencies: pandas + pyyaml. Everything else is optional extras.

## Install

```bash
pip install -e ".[dev]"        # core + test tools
pip install -e ".[parquet]"    # pyarrow, for parquet files
pip install -e ".[excel]"      # openpyxl, for .xlsx
pip install -e ".[sql]"        # duckdb, for SQL across folder files
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
df = ts.query("SELECT * FROM clients JOIN refs USING (id)")  # needs localdb[sql]

ts = localdb.tables("data/warehouse.sqlite")     # sqlite works the same way
```

Ambiguous stems (`clients.csv` + `clients.parquet`) raise rather than guess;
a `.sqlite` file inside a folder is its own `Tables`, not a table.

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

Shipped key cleaners: `postal_code` (case/spaces/ZIP+4), `fsa` (extracts the
FSA from a postal code), `client_id`, `phone` (international digits, NANP
country-code strip), `email`. Register your own:

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

Similarity is stdlib `difflib` (exact = 1.0); missing fields are excluded
from a pair's score. Always pass `block_on` — without it every left/right
combination is a candidate.

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

## Known limits

- Whole files load into memory — `chunksize=` is the passthrough workaround
- Zip members are readable but not SQL-joinable via duckdb
- `postal_code` cleaner is North-America-oriented; international addresses
  need custom kinds
- Fuzzy scoring suits up to ~100k candidate pairs with `block_on`; beyond
  that a recordlinkage/Splink backend is the escalation path

## Development

```bash
.venv/Scripts/python -m pytest       # Windows venv; plain `pytest` elsewhere
.venv/Scripts/python -m ruff check src tests
```

See `PLAN.md` for scope, `TODO.md` for status and next steps.
