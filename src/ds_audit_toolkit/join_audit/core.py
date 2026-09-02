"""Match report (exact via datacompy) + fuzzy fallback (recordlinkage/Splink).

datacompy integration (audited against datacompy v1):
    - Entry point: `datacompy.PandasCompare(df1, df2, join_columns=key,
      abs_tol=..., rel_tol=...)`. Per-column tolerances are supported
      (e.g. `abs_tol={"balance": 0.01}`) — the mechanism for the
      rounding-vs-genuinely-wrong distinction in PLAN.md section 6.
    - Constraint: the join key must be unique per row — datacompy errors on
      duplicates. `check_key_quality` must gate `audit_join` (fail fast or
      dedupe first).
    - `compare.build_report_data()` returns a typed ReportData
      (row_summary, mismatch_stats) with .to_dict()/.render()/.save() —
      the structured source feeding JoinAuditResult and the HTML report.
"""

from typing import Any

from ds_audit_toolkit.types import JoinAuditResult, KeyQualityReport


def check_key_quality(left: Any, right: Any, key: str) -> KeyQualityReport:
    """Pre-join checks: duplicate keys, null keys, dtype mismatches between sides.

    Dtype mismatches between sides are a common silent cause of false
    non-matches. Must run before audit_join: datacompy refuses duplicate
    join keys.
    """
    raise NotImplementedError("key quality checks land in Phase 2")


def audit_join(left: Any, right: Any, key: str, match_threshold: float = 0.95,
               fuzzy_fallback: bool = True, abs_tol: float = 0.0,
               rel_tol: float = 0.0) -> JoinAuditResult:
    """Join two datasets and audit match quality.

    Builds a datacompy exact-match report (row counts, unmatched keys,
    column-level mismatch rates, dtype mismatches). If the match rate falls
    below `match_threshold` and `fuzzy_fallback` is set, triggers a fuzzy pass
    (recordlinkage; Splink for larger volumes) and reports match confidence
    instead of a binary yes/no.

    `abs_tol`/`rel_tol` pass through to PandasCompare; per-column values
    (the long-term form per PLAN.md section 6) start as a flat default.
    """
    raise NotImplementedError("exact-match audit lands in Phase 2; fuzzy in Phase 3")
