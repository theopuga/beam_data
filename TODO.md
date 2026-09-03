# TODO — remaining work

Phases 0–7 of `PLAN.md` are complete (75 tests passing, CI green on Python
3.10–3.13). What's left is real-world validation and the carry-forward items
below.

## Phase 8 — pilot (blocked on inputs, not code)

- [ ] Pick the pilot work project and dataset pair
- [ ] Confirm which DBs are first (Postgres only, or also Snowflake/SQL Server)
      — resolves PLAN.md §8 question 1
- [ ] Obtain read-only credentials; store as env vars (`${VAR}` refs in the
      YAML — never commit secrets)
- [ ] `pip install -e ".[postgresql]"` (or the matching driver extra)
- [ ] Write the pilot `config/*.yaml` (sources, keys, key_types, thresholds)
- [ ] Run `run_audit()` end-to-end against both real sources — this also
      closes Phase 1's "working against 2 real internal sources" deliverable
- [ ] Sanity-check the flag report by hand (flags are advisory, not drops)

## Validation & tuning (falls out of the pilot)

- [ ] Verify the shipped key cleaners (`postal_code`, `fsa`, `client_id`,
      `phone`, `email`) against real messy values; register project-specific
      kinds where they fall short
- [ ] Replace placeholder thresholds with real numbers from pilot data:
      `match_threshold` (0.95) and fuzzy `fuzzy_score_threshold` (0.85)
      — resolves PLAN.md §8 question 2
- [ ] Introduce per-column tolerance dicts (`abs_tol={"amount": 0.01}`) once
      real rounding-diff noise appears (PLAN.md §6)
- [ ] Decide where run reports live — local `reports/` vs shared location
      — resolves PLAN.md §8 question 3

## Tech debt / carry-forward (from PLAN.md §6/§9)

- [ ] Revisit the `scipy<1.16` pin when IT allowlists the newer wheels
      (local WDAC policy blocks their DLLs; CI is unaffected)
- [ ] recordlinkage is stale/pandas-only — switch fuzzy fallback to Splink if
      it blocks a Python upgrade or volumes outgrow it
- [ ] Match auditing is row-level, not semantic — $0.01 rounding vs wrong
      value both count as mismatch until per-column tolerances are tuned
- [ ] Governance: outputs are report files only; if this ever needs to be
      compliance-defensible, add a structured run log (tracked table) per
      PLAN.md §6
