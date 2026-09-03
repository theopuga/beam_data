# localdb — project plan

## 1. Problem statement

Datasets are downloaded ahead of time — CSV/Parquet/JSON extracts, SQLite
files — and every script re-solves the same trivial-but-annoying plumbing:
finding files, remembering formats, hardcoding paths, ad hoc pd.read_* calls.
There is no single "open the database" step for data that is already local.

**Goal:** a small Python package that treats a folder of downloaded data
files (or a SQLite file) as a database: discover tables by name, read them
into pandas, optionally run SQL across files. No connections, no servers.

## 2. Scope (v1)

In scope:
- `read(path)` — one file -> DataFrame, format chosen by extension
- `connect(folder_or_sqlite)` — folder-as-database: `list_tables()`,
  `get_table(name)`; SQLite files queried via stdlib sqlite3
- `query(sql)` — SQL across the folder's files via DuckDB (`sql` extra);
  SQLite via sqlite3 directly
- Extensible reader registry (`register_reader`) so "other types of data
  files" are one registration away
- Optional YAML catalog mapping dataset names to paths, with `${VAR}` env
  expansion so absolute locations stay out of committed files

Out of scope (v1):
- Live database connections (the data is already downloaded)
- Writing/syncing back to sources
- Schema validation, joins, audits — the prior toolkit scope was retired

## 3. Architecture

```
src/localdb/
├── readers/core.py    # extension -> pandas loader registry (csv, tsv, parquet,
│                      # excel, json, sqlite) + read()
├── database.py        # Database: folder-as-db or SQLite file; list/get/query
├── catalog.py         # optional YAML: dataset name -> path
└── __init__.py        # public API: read, connect, Database, register_reader
```

Dependency direction: `database` -> `readers`; `catalog` standalone; no
module imports the package root (no cycles).

## 4. Usage

```python
import localdb

df = localdb.read("data/clients.csv")            # single file

db = localdb.connect("data/downloads/")          # folder as database
db.list_tables()                                  # ["clients", "fsa_lookup", ...]
df = db.get_table("clients")                      # by stem, any format
df = db.query("SELECT * FROM clients JOIN refs USING (id)")  # needs localdb[sql]
```

```yaml
# catalog.yaml — datasets declared once, referenced by name
clients: data/clients.csv
fsa_lookup: ${DOWNLOAD_DIR}/fsa_lookup.parquet
```

```python
tables = localdb.load_catalog("catalog.yaml")
df = localdb.read(tables["fsa_lookup"])
```

## 5. Milestones

| Phase | Deliverable | Notes |
|---|---|---|
| 0 | Package skeleton, pyproject, CI | done |
| 1 | `readers` + `Database` (folder + sqlite) | done |
| 2 | YAML catalog + duckdb `query()` | done |
| 3 | Real-data pilot on the actual downloaded sets | next: needs the real folder |

## 6. Known limitations

- Whole files load into memory; no chunking/sampling yet
- `get_table` prefers nothing on ambiguous stems — it raises; rename files
- duckdb views only cover csv/tsv/parquet/json (excel files still readable
  via `get_table`, just not SQL-joinable)
- Reader set is fixed at import; per-project readers register at runtime
