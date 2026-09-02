# ds-audit-toolkit — Project Plan

## 1. Problem statement

Every data science project starts with the same unglamorous work: pull data from
multiple sources, standardize join keys, merge, audit the merge for errors, validate
the resulting schema, and then figure out which features are safe to feed a model
(vs. which are noise, duplicates, or leakage). Today this is rebuilt from scratch
per project, mostly by hand, with no consistent audit trail.

**Goal:** a single internal package that turns this checklist into one reusable,
config-driven pipeline, producing a report artifact at each stage — so joins,
validation, and feature selection are governed and reproducible instead of ad hoc.

## 2. Scope (v1)

In scope:
- Connect to multiple relational sources with one interface
- Standardize common key types (postal code / FSA, client IDs, phone, etc.)
- Join two datasets on a key, with an automated match-quality audit
- Fuzzy-match fallback when exact-key match rate is too low
- Schema validation (auto-drafted, then checked in and versioned)
- Feature flagging for modeling: leakage, non-predictive, target-correlated
- One orchestrated pipeline call producing a single report per run

Out of scope for v1 (revisit later):
- Automated fixing/resolution of mismatches (human judgment stays in the loop)
- Multi-way (3+ dataset) native audits — chain pairwise for now
- Non-tabular data (text, images)
- Streaming / real-time sources

## 3. Architecture

```
ds-audit-toolkit/
├── connectors/          # pull from DBs/files into a common dataframe interface
├── standardize/          # key formatting & type coercion registry
├── join_audit/            # match report (exact) + fuzzy fallback + confidence scores
├── schema_validate/     # pandera-based rule enforcement, auto-drafted schemas
├── feature_flags/       # leakage / non-predictive / target detection
├── reporting/             # renders one HTML/markdown report per pipeline run
├── config/                  # YAML pipeline configs (per project/dataset pair)
├── tests/
├── pipeline.py            # orchestrates the above end-to-end
├── pyproject.toml
└── README.md
```

### Module responsibilities

**connectors/**
- `get_table(conn_str, table_or_query) -> pd.DataFrame`
- SQLAlchemy under the hood — one function signature regardless of DB engine
- Sources declared in a YAML config, not hardcoded, so adding a source is a config
  line, not new code

**standardize/**
- Registry of known key types, each with its own cleaning function:
  `standardize(df, column, kind="postal_code")`
- Ship with: `postal_code`, `fsa`, `client_id`, `phone`, `email`
- Easy to register a new `kind` without touching core logic

**join_audit/**
- Wraps `datacompy` for the exact-match report (row counts, unmatched keys,
  column-level mismatch rates, dtype mismatches)
- If match rate falls below a configurable threshold (e.g. 95%), automatically
  triggers a fuzzy pass via `recordlinkage` (or `Splink` for larger volumes) and
  reports match confidence instead of a binary yes/no
- Pre-join key-quality checks: duplicate keys, null keys, dtype mismatches between
  sides (a common silent cause of false non-matches)

**schema_validate/**
- `pandera`-based validation
- On first run against a new dataset: auto-draft a schema (infer dtype,
  nullability, uniqueness) and write it to `config/schemas/<dataset>.py`
- On subsequent runs: enforce the checked-in schema (now hand-editable and
  version-controlled, not regenerated blindly)

**feature_flags/** — the core value-add beyond existing tools
- *Leakage — adversarial validation*: train XGBoost to classify train vs.
  holdout (or train vs. out-of-time split, if a time column exists). Features
  with high importance in that model are flagged — they're encoding row
  provenance, not signal.
- *Leakage — target correlation*: flag features with near-1.0 correlation
  (numeric) or mutual information (categorical) with the target — catches
  accidental duplicate/post-outcome columns.
- *Leakage — temporal*: if columns are tagged with an "available-as-of"
  timestamp, flag any feature that becomes available after the target event.
- *Non-predictive*: constant / near-zero-variance columns
  (`feature-engine DropConstantFeatures`), duplicate columns
  (`DropDuplicateFeatures`), low permutation importance.
- Output is a **flag report**, not an auto-drop — columns get a `leak_score`,
  `predictive_score`, and `reason`; the analyst decides what to exclude.

**reporting/**
- One HTML/markdown report per pipeline run combining: join audit results,
  schema validation results, feature flag table
- Meant to be attachable to a PR, doc, or review — audit evidence, not just
  console output

**pipeline.py**
- `run_audit(config_path)` → connects, standardizes, joins + audits, validates
  schema, and (if `target_column` is set in config) runs feature flagging
- Single entry point; everything else is composable if someone only needs one
  stage

## 4. Config-driven usage (target UX)

```yaml
# config/client_geo_join.yaml
sources:
  clients:
    conn: postgresql://.../warehouse
    table: clients
    key: postal_code
    key_type: postal_code
  geo:
    conn: postgresql://.../geo
    table: fsa_lookup
    key: fsa
    key_type: fsa

join:
  match_threshold: 0.95
  fuzzy_fallback: true

target_column: churned      # omit to skip feature flagging
time_column: signup_date    # optional, enables temporal leakage checks
```

```python
from ds_audit_toolkit import run_audit
report = run_audit("config/client_geo_join.yaml")
report.save("reports/client_geo_join.html")
```

## 5. Milestones

| Phase | Deliverable | Notes |
|---|---|---|
| 0 | Repo scaffold, `pyproject.toml`, CI skeleton | empty modules, tests stubbed |
| 1 | `connectors` + `standardize` | working against 2 real internal sources |
| 2 | `join_audit` (exact match via datacompy) | pre-join key checks + match report |
| 3 | `join_audit` fuzzy fallback | recordlinkage integration, threshold trigger |
| 4 | `schema_validate` | auto-draft + checked-in pandera schemas |
| 5 | `feature_flags` v1 | non-predictive + target correlation flags |
| 6 | `feature_flags` v2 | adversarial validation + temporal leakage |
| 7 | `reporting` + `pipeline.py` | single end-to-end config-driven call |
| 8 | Pilot on one real work project | validate against an actual audit you'd otherwise do by hand |

## 6. Known limitations to carry forward (from prior tool evaluation)

- Match auditing is still row-level, not semantic — a $0.01 rounding diff and a
  genuinely wrong value both show up as "mismatch"; tolerance thresholds need
  per-column tuning over time.
- Fuzzy matching adds compute cost — fine for pairwise audits, not built for
  warehouse-scale (10s of millions of rows) without sampling or a Spark backend.
- Feature flags are advisory, not authoritative — adversarial validation and
  correlation thresholds catch *likely* leakage, not certain leakage; still
  requires a human sanity check before dropping a feature.
- Governance: v1 produces a report file, not a queryable audit log. If this
  needs to be defensible for compliance later, revisit storing run outputs in a
  structured log (e.g., append to a tracked table) rather than only HTML.

## 7. Dependencies (initial)

`sqlalchemy`, `datacompy`, `recordlinkage`, `pandera`, `feature-engine`,
`xgboost`, `scikit-learn`, `pandas`, `pyyaml`, `jinja2` (reporting)

## 8. Open questions

- Which internal DBs need connectors first (Postgres only, or also
  Snowflake/SQL Server)?
- Match-rate threshold for triggering fuzzy fallback — 95% is a placeholder,
  needs a real number from a pilot dataset.
- Where do run reports live — local `reports/` folder, or pushed somewhere
  shared (Confluence, S3, internal dashboard)?
