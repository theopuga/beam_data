# TODO — localdb

Package is functional end-to-end (folder-as-db, sqlite, catalog, duckdb
queries, 30+ tests). Remaining:

## Next

- [ ] Pilot on the real downloaded data folder — the actual file set this is
      meant for; may surface format quirks (encodings, headers, dates)
- [ ] Add readers for any project-specific file types found in the pilot
      (`register_reader`)
- [ ] Consider chunking/sampling for files too big for memory
- [ ] Optional: caching layer (parquet cache of slow-to-parse files)

## Later / ideas

- [ ] Lazy table proxies (read on access) if startup cost matters
- [ ] Column pruning pushdown for parquet (`get_table(name, columns=[...])`)
- [ ] Publish internally (or to PyPI) once the pilot validates the API
