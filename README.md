# localdb

Treat a folder of already-downloaded data files — CSV, Parquet, JSON, Excel,
or a SQLite file — as a database. No connections, no servers: the files are
the database.

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

db = localdb.connect("data/downloads/")          # a folder is the database
db.list_tables()                                  # by file stem
df = db.get_table("clients")                      # any registered format
df = db.query("SELECT * FROM clients JOIN refs USING (id)")  # needs localdb[sql]

db = localdb.connect("data/warehouse.sqlite")    # sqlite works the same way
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

## Development

```bash
.venv/Scripts/python -m pytest       # Windows venv; plain `pytest` elsewhere
.venv/Scripts/python -m ruff check src tests
```

See `PLAN.md` for scope and `TODO.md` for what's next.
