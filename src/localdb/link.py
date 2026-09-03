"""Link tables on shared identifiers: standardize keys, check quality, join.

The linking workflow for downloaded data:
    1. standardize each side's key (postal codes, FSAs, client ids, ...)
    2. report key quality (duplicates, nulls, dtype mismatches between sides)
    3. join and report match coverage — which keys found a partner, which
       did not (sampled)

Duplicates are reported, not fatal: one-to-many links (many clients per
FSA) are normal. The analyst decides what to do with the report.
"""

from dataclasses import dataclass, field

import pandas as pd

from localdb.keys import standardize

_MAX_UNMATCHED_SAMPLE = 100
_VALID_HOW = {"inner", "left", "right", "outer"}


@dataclass
class LinkResult:
    """The joined table plus the link report — advisory evidence, not a gate.

    matched_rows counts driving-side rows that found a partner (equal to the
    joined row count for how="inner" when keys are unique).
    """

    joined: pd.DataFrame
    left_table: str
    right_table: str
    on: str
    how: str
    matched_rows: int
    match_rate: float
    unmatched_left: list[str] = field(default_factory=list)
    unmatched_right: list[str] = field(default_factory=list)
    duplicates: dict[str, int] = field(default_factory=dict)
    nulls: dict[str, int] = field(default_factory=dict)
    dtype_mismatches: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"LinkResult({self.left_table} <-> {self.right_table} on {self.on!r} "
            f"[{self.how}]: {self.matched_rows} matched rows, "
            f"match_rate={self.match_rate:.3f})"
        )


def _check_column(df: pd.DataFrame, column: str, side: str) -> None:
    if column not in df.columns:
        available = ", ".join(map(str, df.columns))
        raise KeyError(f"{side} table has no column {column!r}; available: {available}")


def _key_quality(left: pd.DataFrame, left_on: str,
                 right: pd.DataFrame, right_on: str) -> tuple[dict, dict, list[str]]:
    duplicates = {
        "left": int(left[left_on].duplicated().sum()),
        "right": int(right[right_on].duplicated().sum()),
    }
    nulls = {
        "left": int(left[left_on].isna().sum()),
        "right": int(right[right_on].isna().sum()),
    }
    dtype_mismatches = (
        [f"{left_on}: {left[left_on].dtype} (left) vs {right_on}: {right[right_on].dtype} (right)"]
        if str(left[left_on].dtype) != str(right[right_on].dtype)
        else []
    )
    return duplicates, nulls, dtype_mismatches


def link_tables(left: pd.DataFrame, right: pd.DataFrame, left_on: str,
                right_on: str | None = None, left_key_type: str | None = None,
                right_key_type: str | None = None, how: str = "inner",
                left_name: str = "left", right_name: str = "right") -> LinkResult:
    """Join two frames on identifier columns and report link quality.

    Args:
        left_on / right_on: key column names (right_on defaults to left_on).
        left_key_type / right_key_type: optional standardize kinds applied to
            each side's key BEFORE joining (e.g. both "fsa" to link postal
            codes against an FSA lookup).
        how: merge strategy (inner/left/right/outer).
    """
    right_on = right_on or left_on
    if how not in _VALID_HOW:
        raise ValueError(f"how must be one of {sorted(_VALID_HOW)}, got {how!r}")
    _check_column(left, left_on, "left")
    _check_column(right, right_on, "right")
    duplicates, nulls, dtype_mismatches = _key_quality(left, left_on, right, right_on)

    left = left.copy()
    right = right.copy()
    if left_key_type:
        standardize(left, left_on, left_key_type)
    if right_key_type:
        standardize(right, right_on, right_key_type)

    try:
        joined = left.merge(right, left_on=left_on, right_on=right_on, how=how,
                            suffixes=("_left", "_right"))
    except ValueError as exc:
        detail = dtype_mismatches[0] if dtype_mismatches else str(exc)
        raise ValueError(
            f"cannot merge on key {left_on!r}: {detail}; "
            "align dtypes or pass a key_type to standardize"
        ) from exc

    left_keys = set(left[left_on].dropna())
    right_keys = set(right[right_on].dropna())
    matched = left_keys & right_keys
    n_total = max(len(left_keys), len(right_keys))
    match_rate = len(matched) / n_total if n_total else 1.0
    if how == "right":
        matched_rows = int(right[right_on].isin(left_keys).sum())
    else:
        matched_rows = int(left[left_on].isin(right_keys).sum())
    unmatched_left = [str(k) for k in sorted(left_keys - right_keys, key=str)[:_MAX_UNMATCHED_SAMPLE]]
    unmatched_right = [str(k) for k in sorted(right_keys - left_keys, key=str)[:_MAX_UNMATCHED_SAMPLE]]

    return LinkResult(
        joined=joined,
        left_table=left_name,
        right_table=right_name,
        on=left_on if left_on == right_on else f"{left_on} = {right_on}",
        how=how,
        matched_rows=matched_rows,
        match_rate=float(match_rate),
        unmatched_left=unmatched_left,
        unmatched_right=unmatched_right,
        duplicates=duplicates,
        nulls=nulls,
        dtype_mismatches=dtype_mismatches,
    )
