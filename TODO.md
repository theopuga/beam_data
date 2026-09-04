# TODO — localdb

Package is functional end-to-end and piloted on real data (74 tests,
including regression tests against test_data/ that skip in CI).

## Pilot round 4 — done (2026-09-04, barcodes + FEBRL record-linkage benchmark)

- [x] `barcode_client_ids.csv`: integer dtype inference **strips leading
      zeros** from barcode client ids — ids must be read with
      `dtype={'client_id': 'string'}`; documented in tests
- [x] `register_kind` extensibility proven: an `ean13_valid` kind (check-digit
      validation) correctly flags the corrupted row
- [x] `febrl4_A/B.csv` (the standard record-linkage benchmark): ground truth
      extracted — 5000 true pairs via `rec_id` stem; exact full-row overlap 0;
      exact-link ceiling collapses 0.963 (postcode) → 0.512 (postcode+surname
      +dob) as corruption hits more fields

### Decision unlocked by round 4 — RESOLVED

- [x] **Fuzzy fallback built** — `localdb.fuzzy_link_tables` (stdlib difflib,
      zero new dependencies): multi-column weighted similarity scoring,
      union blocking (`block_on` list), threshold classification,
      `best_matches()` per left row. FEBRL4 acceptance: **recall 0.807 /
      precision 0.950** at threshold 0.75 vs the 0.512 exact-link ceiling,
      validated against 5000 known pairs (regression-tested). Scaling beyond
      ~100k candidate pairs (recordlinkage/Splink) remains a Later item.

## Pilot round 3 — done (2026-09-04, messy CSV + Companies House zips + HF parquet)

- [x] `messy_quebec_extract.csv`: kwargs passthrough handles latin-1,
      semicolons, preamble rows, French decimals; `client_id` cleaner
      preserves house formats (`C-00042`); utf-8 failure is loud, not silent
- [x] Built-in **zip reader** (single-member csv/tsv/txt, `member=` for
      multi-member); Companies House 70MB zip reads targeted columns
- [x] Memory question settled pragmatically: 850k rows/2.9s targeted read;
      5.69M-row full scan of the 2.8GB zip in 18.2s via `chunksize=` passthrough
- [x] Real **parquet** via HuggingFace datasets-server (day shards); SQL
      UNION ALL across shards works; parquet dtypes preserved (datetime64
      tz-aware, int32)

### Follow-ups from round 3

- [ ] Companies House headers have alternating leading spaces
      (` CompanyNumber`) — consider a `clean_headers=True` read option
- [ ] `montant`-style mixed decimal formats stay object dtype — advisory
      only, but a validation helper could flag "column should be numeric"
- [ ] Zip members are not SQL-queryable via duckdb (skipped with warning) —
      acceptable; note in docs

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

Both original data blockers are resolved (client-id formats: barcodes, round
4; low-match-rate data: FEBRL, round 4). Remaining data needs are
use-case-driven only.

## Later

- [ ] Optional: caching layer (parquet cache of slow-to-parse files)
- [ ] Column pruning pushdown for parquet (`ts.get(name, columns=[...])`)
- [ ] Publish internally (or to PyPI) once the API feels right


