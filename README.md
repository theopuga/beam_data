# ds-audit-toolkit

Config-driven pipeline that turns the per-project data-prep checklist — pull,
standardize keys, join, audit the merge, validate schema, flag features — into
one reusable, reproducible workflow with a report artifact at each stage.

See `PLAN.md` for the full problem statement, scope, and milestones.

## Install

```bash
pip install -e ".[dev]"
```

## Usage (target UX)

```python
from ds_audit_toolkit import run_audit

report = run_audit("config/client_geo_join.yaml")
report.save("reports/client_geo_join.html")
```

Pipeline configs are YAML (see `config/client_geo_join.yaml`): sources, join
keys/types, match threshold, and optional target/time columns for feature
flagging.

## Layout

| Module | Responsibility |
|---|---|
| `connectors/` | Pull from DBs/files into a common dataframe interface (SQLAlchemy) |
| `standardize/` | Key formatting & type coercion registry (`postal_code`, `fsa`, `client_id`, ...) |
| `join_audit/` | Match report (exact via datacompy) + fuzzy fallback + confidence scores |
| `schema_validate/` | Pandera rule enforcement; auto-drafted schemas checked into `config/schemas/` |
| `feature_flags/` | Leakage (adversarial, target-correlation, temporal) / non-predictive detection |
| `reporting/` | One HTML/markdown report per pipeline run |
| `pipeline.py` | `run_audit(config_path)` — orchestrates the above end-to-end |

## Status

Phase 0 — repo scaffold; modules are stubbed. Milestones tracked in `PLAN.md`.

## Development

```bash
pytest        # run tests
ruff check src tests
```
