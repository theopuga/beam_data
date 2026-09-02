"""Match report (exact via datacompy) + fuzzy fallback (recordlinkage/Splink).

datacompy integration (audited against datacompy v1):
    - Entry point: `datacompy.PandasCompare(df1, df2, join_columns=key,
      abs_tol=..., rel_tol=...)`. Tolerances accept flat floats or per-column
      dicts (e.g. `abs_tol={"balance": 0.01}`) — the mechanism for the
      rounding-vs-genuinely-wrong distinction in PLAN.md section 6.
    - Constraint: the join key must be unique per row — datacompy errors on
      duplicates. `check_key_quality` gates `audit_join` (fail fast on
      duplicates; nulls and key dtype mismatches are reported, not fatal).
    - `compare.build_report_data()` returns a typed ReportData (row_summary,
      mismatch_stats) with .to_dict()/.render()/.save() —
      the structured source feeding JoinAuditResult and the HTML report.

Match-rate definition: common_rows / max(len(left), len(right)) — rows whose
KEY exists on both sides, regardless of column value differences. Value
mismatches are reported separately per column.
"""


import datacompy
import pandas as pd

from ds_audit_toolkit.types import JoinAuditResult, KeyQualityReport

_MAX_UNMATCHED_SAMPLE = 100


def check_key_quality(left: pd.DataFrame, right: pd.DataFrame, key: str) -> KeyQualityReport:
    """Pre-join checks: duplicate keys, null keys, key dtype mismatches.

    Dtype mismatches between sides are a common silent cause of false
    non-matches. Must run before audit_join: datacompy refuses duplicate
    join keys.
    """
    for name, df in (("left", left), ("right", right)):
        if key not in df.columns:
            raise ValueError(f"{name} frame is missing key column {key!r}")
    return KeyQualityReport(
        duplicates={
            "left": int(left[key].duplicated().sum()),
            "right": int(right[key].duplicated().sum()),
        },
        nulls={
            "left": int(left[key].isna().sum()),
            "right": int(right[key].isna().sum()),
        },
        dtype_mismatches=(
            [f"{key}: {left[key].dtype} (left) vs {right[key].dtype} (right)"]
            if str(left[key].dtype) != str(right[key].dtype)
            else []
        ),
    )


def audit_join(left: pd.DataFrame, right: pd.DataFrame, key: str,
               match_threshold: float = 0.95, fuzzy_fallback: bool = True,
               abs_tol: float | dict[str, float] = 0.0,
               rel_tol: float | dict[str, float] = 0.0,
               left_name: str = "left", right_name: str = "right") -> JoinAuditResult:
    """Join two datasets and audit match quality.

    Builds a datacompy exact-match report (row counts, unmatched keys,
    column-level mismatch rates, dtype mismatches). If the match rate falls
    below `match_threshold` and `fuzzy_fallback` is set, the fuzzy pass
    (recordlinkage; Splink for larger volumes) reports match confidence
    instead of a binary yes/no — Phase 3.

    `abs_tol`/`rel_tol` pass through to PandasCompare as flat defaults or
    per-column dicts.
    """
    key_quality = check_key_quality(left, right, key)
    duplicates = {side: n for side, n in key_quality.duplicates.items() if n}
    if duplicates:
        raise ValueError(
            "Duplicate key values break the exact-match audit "
            f"(datacompy requires unique join keys); dedupe first: {duplicates}"
        )

    compare = datacompy.PandasCompare(
        left,
        right,
        join_columns=key,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
        df1_name=left_name,
        df2_name=right_name,
    )
    data = compare.build_report_data()
    row_summary = data.row_summary
    n_total = max(len(left), len(right))
    match_rate = float(row_summary.common_rows) / n_total if n_total else 1.0

    column_mismatch_rates: dict[str, float] = {}
    if row_summary.common_rows:
        column_mismatch_rates = {
            stat.column: float(stat.unequal_cnt) / float(row_summary.common_rows)
            for stat in data.mismatch_stats.stats
        }

    unmatched = sorted(set(left[key].dropna()) - set(right[key].dropna()), key=str)
    unmatched += sorted(set(right[key].dropna()) - set(left[key].dropna()), key=str)
    unmatched = [str(v) for v in unmatched[:_MAX_UNMATCHED_SAMPLE]]

    result = JoinAuditResult(
        match_rate=match_rate,
        match_threshold=match_threshold,
        matched_rows=int(row_summary.common_rows),
        unmatched_keys=unmatched,
        column_mismatch_rates=column_mismatch_rates,
        key_quality=key_quality,
        fuzzy_used=False,
        datacompy_report=data.to_dict(),
    )
    if match_rate < match_threshold and fuzzy_fallback:
        raise NotImplementedError(
            f"Match rate {match_rate:.3f} is below threshold {match_threshold:.2f}; "
            "fuzzy fallback lands in Phase 3"
        )
    return result
