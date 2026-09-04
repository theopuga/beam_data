# TODO — localdb

Package is functional end-to-end (folder-as-db, sqlite, catalog, duckdb
queries, identifier linking, 50 tests). Remaining:

## Next: pilot on real data — data shopping list

Find files matching this checklist so the pilot exercises everything:

- [ ] A folder of downloaded extracts to act as the table set (mix of
      formats if possible: at least one `.csv` and one `.parquet`; a
      `.json` and/or `.xlsx` file exercises the other readers)
- [ ] Optionally one `.sqlite` / `.db` file (exercises the stdlib SQL path)
- [ ] A table with a **postal code** column (messy values welcome — mixed
      case, spaces/hyphens, ZIP+4)
- [ ] A table with an **FSA** column (to link against the postal code table)
- [ ] A table with a **client id** column (tests `client_id` cleaner;
      note any house format like leading zeros or prefixes)
- [ ] A table with **phone** and/or **email** columns (tests those cleaners)
- [ ] Two tables that are *known* to share keys — so the link has a right
      answer to compare `match_rate` against
- [ ] Note the largest file's size (tests the memory question: whole-file
      reads vs needing chunking/caching)

### Pilot run (once files are in place)

- [ ] `ts = localdb.tables(folder)` → `ts.names()` — do all expected tables
      show up? any unreadable types → `register_reader`
- [ ] `ts.get(name).head()` per table — encodings, header rows, date parsing
- [ ] `ts.link(...)` on the postal/FSA pair and the client-id pair — record
      `match_rate`, `duplicates`, `nulls`
- [ ] If shipped cleaners miss house formats → `register_kind` with the
      project-specific rule
- [ ] If a file is too big for memory → prioritize chunking/caching next

## Later

- [ ] Fuzzy key fallback for links with low match rates (recordlinkage or
      Splink) — only if the pilot shows exact matching is not enough
- [ ] Consider chunking/sampling for files too big for memory
- [ ] Optional: caching layer (parquet cache of slow-to-parse files)
- [ ] Column pruning pushdown for parquet (`ts.get(name, columns=[...])`)
- [ ] Publish internally (or to PyPI) once the pilot validates the API
