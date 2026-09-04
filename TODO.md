# TODO — localdb

Package is functional end-to-end and piloted on real data (60 tests,
including regression tests against test_data/ that skip in CI).

## Pilot — done (2026-09-04, licence/registration extracts + GeoNames CA)

- [x] Folder discovery incl. `.xlsx`; CSV/XLSX reading
- [x] Link: business 17-18 ↔ 18-19 on `Licence Number` — left coverage 1.000
- [x] Link: individual `Employer Licence` → business — left coverage 1.000
- [x] Link: postal → FSA via `fsa` cleaner — left coverage 0.988
- [x] DuckDB SQL join across real CSV + XLSX (hyphenated stems fixed,
      `read_xlsx` wired in, non-SQL formats now warn instead of vanishing)

### Follow-ups from pilot findings

- [ ] Review the 8 postal codes that failed FSA resolution (`ON`, `Y,O`,
      `337`, `106`, and 4 plausible-but-unmatched FSAs) — decide whether to
      clean upstream or add tolerance rules
- [ ] Short table aliases via `catalog.yaml` (file stems are unwieldy)

## Pilot — done (2026-09-04, chinook.sqlite)

- [x] Stdlib sqlite path: names/get/query, 3-table join validated
- [x] Link on real keys: Invoice → Customer, match_rate 1.000
- [x] `email` and `phone` cleaners on real international data (NANP leading-1
      strip verified on Canadian numbers)

### Follow-ups from chinook findings

- [ ] `postal_code` cleaner is North-America-oriented — it mangles
      international formats (Brazil `12227-000`, Germany `70174`); build
      country-aware kinds if international address linking is needed
- [ ] Documented: a `.sqlite` inside a folder is its own Tables, not a table

## Next — data still to find

- [ ] Files with real **client id** house formats (prefixes, leading zeros,
      check digits) to exercise the `client_id` cleaner
- [ ] A genuinely large file (100MB+) to settle the memory question —
      chunking/caching is the first feature if it hurts
- [ ] A real `.parquet` extract (nested types, zstd, partitioned folders
      sometimes differ from synthetic tests)
- [ ] Deliberately messy data: `latin-1` encoding, junk header rows, mixed
      date formats — all still first encounters

## Later

- [ ] Fuzzy key fallback for links with low match rates (recordlinkage or
      Splink) — only if exact matching proves insufficient
- [ ] Chunking/sampling for files too big for memory
- [ ] Optional: caching layer (parquet cache of slow-to-parse files)
- [ ] Column pruning pushdown for parquet (`ts.get(name, columns=[...])`)
- [ ] Publish internally (or to PyPI) once the API feels right

