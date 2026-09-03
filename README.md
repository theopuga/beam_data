# localdb

Connect to tables you already downloaded. A folder of data files — CSV,
Parquet, JSON, Excel — or a SQLite file is a set of tables you can open by
name and join with SQL. No connections, no servers: the files are the tables.

## Install

```bash
pip install -e ".[dev]"        # core + test tools
pip install -e ".[parquet]"    # pyarrow, for parquet files
pip install -e ".[sql]"        # duckdb, for SQL across files
```

## Usage

```python
import localdb

df = localdb.read("data/clients.csv")            # one file, format by extension

ts = localdb.tables("data/downloads/")           # connect to the folder's tables
ts.names()                                       # by file stem
df = ts.get("clients")                           # any registered format
df = ts.query("SELECT * FROM clients JOIN refs USING (id)")  # needs localdb[sql]

ts = localdb.tables("data/warehouse.sqlite")     # sqlite works the same way
```

Datasets can be declared once in a YAML catalog:

```yaml
# catalog.yaml
clients: data/clients.csv
fsa_lookup: ${DOWNLOAD_DIR}/fsa_lookup.parquet
```

```python
tables = localdb.load_catalog("catalog.yaml")
df = localdb.read(tables["fsa_lookup"])
```

Custom file types register one reader:

```python
localdb.register_reader("myext", my_loader_fn)
```

## Linking tables on identifiers

The end-goal workflow: connect different files on FSA, client id, postal
code, etc. Keys are standardized first (format messiness removed), quality
is reported, and the joined table comes back with a match report.

```python
result = ts.link("clients", "fsa_lookup",
                 left_on="postal_code", right_on="fsa",
                 left_key_type="fsa", right_key_type="fsa")

result.joined          # the merged DataFrame
result.match_rate      # share of keys found on both sides
result.unmatched_left  # sample of keys with no partner
result.duplicates      # per-side duplicate key counts
result.nulls           # per-side null key counts
```

Shipped key cleaners: `postal_code`, `fsa`, `client_id`, `phone`, `email`.
Register your own with `localdb.register_kind("kind", fn)`. Linking is
advisory: duplicates and mismatches are reported, never dropped silently.

## Development

```bash
.venv/Scripts/python -m pytest       # Windows venv; plain `pytest` elsewhere
.venv/Scripts/python -m ruff check src tests
```

See `PLAN.md` for scope and `TODO.md` for what's next.
