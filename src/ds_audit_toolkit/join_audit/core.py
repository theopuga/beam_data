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
import recordlinkage as rl

from ds_audit_toolkit.types import JoinAuditResult, KeyQualityReport

_MAX_UNMATCHED_SAMPLE = 100
_FUZZY_DEFAULT_SCORE_THRESHOLD = 0.85
_FUZZY_FULL_INDEX_MAX_PAIRS = 1_000_000
_FUZZY_SORTED_NEIGHBOURHOOD_WINDOW = 5


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


def _fuzzy_key_confidence(
    left_keys: pd.Series, right_keys: pd.Series, key: str, score_threshold: float
) -> dict[str, float]:
    """Best Jaro-Winkler score per left key that fuzzily matches a right key.

    Both series hold the keys that survived the exact pass (unique values per
    side — the duplicate gate already ran). Candidate pairs come from a full
    index while the universe is small (no pair can be missed); larger volumes
    fall back to a sorted-neighbourhood index on the key. recordlinkage needs
    unique indexes, so temporary positional-indexed copies are compared.
    `Compare.string` is called without `threshold` on purpose: any non-None
    threshold (even 0.0) binarizes the scores in recordlinkage 0.16, while
    None keeps the continuous 0-1 Jaro-Winkler values.

    Returns {} when there are no candidates, no pairs, or no pair reaching
    `score_threshold`.
    """
    lframe = left_keys.dropna().to_frame(name=key).reset_index(drop=True)
    rframe = right_keys.dropna().to_frame(name=key).reset_index(drop=True)
    if lframe.empty or rframe.empty:
        return {}
    indexer = rl.Index()
    if len(lframe) * len(rframe) <= _FUZZY_FULL_INDEX_MAX_PAIRS:
        indexer.full()
    else:
        indexer.sortedneighbourhood(on=key, window=_FUZZY_SORTED_NEIGHBOURHOOD_WINDOW)
    pairs = indexer.index(lframe, rframe)
    if len(pairs) == 0:
        return {}
    comparer = rl.Compare()
    comparer.string(key, key, method="jarowinkler", label="score")
    scores = comparer.compute(pairs, lframe, rframe)["score"]
    passing = scores[scores >= score_threshold]
    if passing.empty:
        return {}
    best_per_left = passing.groupby(level=0).max()
    return {str(lframe.at[pos, key]): float(score) for pos, score in best_per_left.items()}


def audit_join(left: pd.DataFrame, right: pd.DataFrame, key: str,
               match_threshold: float = 0.95, fuzzy_fallback: bool = True,
               abs_tol: float | dict[str, float] = 0.0,
               rel_tol: float | dict[str, float] = 0.0,
               left_name: str = "left", right_name: str = "right",
               fuzzy_score_threshold: float = _FUZZY_DEFAULT_SCORE_THRESHOLD) -> JoinAuditResult:
    """Join two datasets and audit match quality.

    Builds a datacompy exact-match report (row counts, unmatched keys,
    column-level mismatch rates, dtype mismatches). If the match rate falls
    below `match_threshold` and `fuzzy_fallback` is set, a recordlinkage
    fuzzy pass adds evidence instead of raising: the keys unmatched on each
    side are compared with Jaro-Winkler similarity, `fuzzy_used` flags the
    pass, and `fuzzy_confidence` maps each left key with at least one right
    partner scoring >= `fuzzy_score_threshold` to its best score (float 0-1,
    {} when nothing matches). Match rate and matched rows stay the
    EXACT-match numbers; fuzzy results are additive evidence. Splink remains
    the path for larger volumes.

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
        result.fuzzy_used = True
        result.fuzzy_confidence = _fuzzy_key_confidence(
            left[key][~left[key].isin(right[key])],
            right[key][~right[key].isin(left[key])],
            key,
            fuzzy_score_threshold,
        )
    return result
