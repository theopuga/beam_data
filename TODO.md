# TODO — localdb

Package is functional end-to-end and piloted on real data (53 tests).

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

## Next — data still to find

- [ ] Files with **client id**, **phone**, and/or **email** columns to
      exercise those cleaners against real formats
- [ ] A `.sqlite` / `.db` file (stdlib SQL path is tested synthetically only)
- [ ] A genuinely large file (100MB+) to settle the memory question —
      chunking/caching is the first feature if it hurts

## Later

- [ ] Fuzzy key fallback for links with low match rates (recordlinkage or
      Splink) — only if exact matching proves insufficient
- [ ] Chunking/sampling for files too big for memory
- [ ] Optional: caching layer (parquet cache of slow-to-parse files)
- [ ] Column pruning pushdown for parquet (`ts.get(name, columns=[...])`)
- [ ] Publish internally (or to PyPI) once the API feels right
