# localdb — project plan

## 1. Problem statement

Datasets are downloaded ahead of time — CSV/Parquet/JSON extracts, SQLite
files — and every script re-solves the same trivial-but-annoying plumbing:
finding files, remembering formats, hardcoding paths, ad hoc pd.read_* calls.
There is no single "open the database" step for data that is already local.

**Goal:** a small Python package that connects you to the tables inside a
folder of downloaded data files (or a SQLite file): discover tables by name,
open them into pandas, optionally run SQL across them. No connections, no
servers.

## 2. Scope (v1)

In scope:
- `read(path)` — one file -> DataFrame, format chosen by extension
- `tables(folder_or_sqlite)` — connect to the set of tables: `names()`,
  `get(name)`; SQLite files queried via stdlib sqlite3
- `query(sql)` — SQL joining the tables via DuckDB (`sql` extra);
  SQLite via sqlite3 directly
- `link()` — connect two tables on identifiers (FSA, client id, postal
  code, ...): standardize keys, report duplicates/nulls/dtype mismatches,
  join, and report match coverage with unmatched-key samples
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
├── keys.py            # identifier standardization registry (postal_code, fsa,
│                      # client_id, phone, email) + register_kind
├── link.py            # link_tables/LinkResult: standardize, quality checks,
│                      # join, match coverage report
├── tables.py          # Tables: a folder of files or a SQLite file; names/get/query/link
├── catalog.py         # optional YAML: dataset name -> path
└── __init__.py        # public API: read, tables, link, keys, register_*
```

Dependency direction: `database` -> `readers`; `catalog` standalone; no
module imports the package root (no cycles).

## 4. Usage

```python
import localdb

df = localdb.read("data/clients.csv")            # single file

ts = localdb.tables("data/downloads/")           # connect to the tables
ts.names()                                       # ["clients", "fsa_lookup", ...]
df = ts.get("clients")                           # by stem, any format
df = ts.query("SELECT * FROM clients JOIN refs USING (id)")  # needs localdb[sql]
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
- duckdb views cover csv/tsv/parquet/json/xlsx (xlsx reads all columns as
  varchar); other formats are skipped with a warning
- Reader set is fixed at import; per-project readers register at runtime
