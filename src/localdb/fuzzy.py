"""Fuzzy linking: scored candidate pairs when exact keys cannot match.

Pure-stdlib implementation (difflib) — no extra dependencies. Workflow:
block candidates on a cheap shared column, score each candidate pair as a
weighted average of per-column similarities (exact match = 1.0, otherwise
SequenceMatcher ratio), and keep pairs scoring >= threshold.

Missing values exclude a column from both numerator and denominator, so a
pair is judged only on fields both sides actually have. The result reports
all pairs above threshold; `best_matches()` keeps the highest-scoring
partner per left row.

Ground-truth validation (FEBRL4 benchmark, 5000 known pairs) shows this
beats the exact-link ceiling of 0.512 — see tests/test_real_data.py.
"""

import difflib
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class FuzzyLinkResult:
    """Pairs scoring >= threshold, plus the scoring context."""

    matched: pd.DataFrame
    left_table: str
    right_table: str
    comparisons: list[str]
    threshold: float
    candidate_pairs: int
    match_rate_left: float
    weights: dict[str, float] = field(default_factory=dict)

    def best_matches(self) -> pd.DataFrame:
        """Highest-scoring partner per left row (ties -> first occurrence)."""
        return (
            self.matched.sort_values("score", ascending=False)
            .drop_duplicates("left_index")
            .sort_values("left_index")
            .reset_index(drop=True)
        )

    def __repr__(self) -> str:
        return (
            f"FuzzyLinkResult({self.left_table} <-> {self.right_table} on "
            f"{self.comparisons}: {len(self.matched)} matched pairs "
            f"of {self.candidate_pairs} candidates, "
            f"match_rate_left={self.match_rate_left:.3f})"
        )


def _column_pairs(left: pd.DataFrame, right: pd.DataFrame,
                  on: str | list[str] | None, left_on: list[str] | None,
                  right_on: list[str] | None) -> list[tuple[str, str]]:
    if on is not None:
        cols = [on] if isinstance(on, str) else list(on)
        for name, df in (("left", left), ("right", right)):
            missing = [c for c in cols if c not in df.columns]
            if missing:
                raise KeyError(f"{name} frame lacks comparison columns {missing}")
        return [(c, c) for c in cols]
    if left_on is None or right_on is None:
        raise ValueError("pass on=, or both left_on= and right_on=")
    if len(left_on) != len(right_on):
        raise ValueError("left_on and right_on must have the same length")
    for cols, name, df in ((left_on, "left", left), (right_on, "right", right)):
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise KeyError(f"{name} frame lacks comparison columns {missing}")
    return list(zip(left_on, right_on))


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _candidate_pairs(left: pd.DataFrame, right: pd.DataFrame,
                     block_on: str | list[str]) -> pd.DataFrame:
    """Pairs sharing a value in ANY block column (union semantics).

    Union blocking recovers pairs whose primary block field is itself the
    corrupted one (e.g. block on postcode OR surname).
    """
    blocks = [block_on] if isinstance(block_on, str) else list(block_on)
    out = []
    for b in blocks:
        lb = left[[b]].dropna().reset_index(names="left_index")
        rb = right[[b]].dropna().reset_index(names="right_index")
        out.append(lb.merge(rb, on=b)[["left_index", "right_index"]])
    return pd.concat(out, ignore_index=True).drop_duplicates()


def fuzzy_link_tables(left: pd.DataFrame, right: pd.DataFrame,
                      on: str | list[str] | None = None,
                      left_on: list[str] | None = None,
                      right_on: list[str] | None = None, *,
                      block_on: str | list[str] | None = None,
                      weights: dict[str, float] | None = None,
                      threshold: float = 0.85, max_pairs: int = 5_000_000,
                      left_name: str = "left", right_name: str = "right") -> FuzzyLinkResult:
    """Score candidate pairs across both frames and keep matches >= threshold.

    Args:
        on: column name(s) compared on both sides; or left_on/right_on lists
            for differently-named columns.
        block_on: column(s) restricting candidates to rows sharing a value in
            any of them (strongly recommended; without it every left/right
            pair is a candidate and max_pairs guards the explosion).
        weights: per-comparison-column weights; default equal.
        threshold: pair score (0-1) above which a pair is a match.
    """
    pairs_spec = _column_pairs(left, right, on, left_on, right_on)
    comparisons = [c for c, _ in pairs_spec]
    if weights is not None:
        unknown = set(weights) - set(comparisons)
        if unknown:
            raise ValueError(f"weights reference unknown columns: {sorted(unknown)}")
    w = {c: float((weights or {}).get(c, 1.0)) for c in comparisons}

    if block_on is not None:
        blocks = [block_on] if isinstance(block_on, str) else list(block_on)
        for name, df in (("left", left), ("right", right)):
            missing = [b for b in blocks if b not in df.columns]
            if missing:
                raise KeyError(f"{name} frame lacks block columns {missing}")
        candidates = _candidate_pairs(left, right, blocks)
    else:
        candidates = pd.MultiIndex.from_product(
            [left.index, right.index], names=["left_index", "right_index"]
        ).to_frame(index=False)
    if len(candidates) > max_pairs:
        raise ValueError(
            f"{len(candidates)} candidate pairs exceed max_pairs={max_pairs}; "
            "add a block_on= column to restrict candidates"
        )

    left_str = {c: left[c].fillna("").astype(str).reset_index(drop=True)
                for c, _ in pairs_spec}
    right_str = {c_: right[c_].fillna("").astype(str).reset_index(drop=True)
                 for _, c_ in pairs_spec}

    scores: list[float] = []
    li = candidates["left_index"].to_numpy()
    ri = candidates["right_index"].to_numpy()
    for l_idx, r_idx in zip(li, ri):
        num = den = 0.0
        for c, c_ in pairs_spec:
            a, b = left_str[c].iloc[l_idx], right_str[c_].iloc[r_idx]
            if a == "" or b == "":
                continue
            num += w[c] * _similarity(a, b)
            den += w[c]
        scores.append(num / den if den else 0.0)
    candidates = candidates.assign(score=scores)

    matched = candidates[candidates["score"] >= threshold].reset_index(drop=True)
    match_rate_left = (
        matched["left_index"].nunique() / len(left) if len(left) else 1.0
    )
    return FuzzyLinkResult(
        matched=matched,
        left_table=left_name,
        right_table=right_name,
        comparisons=comparisons,
        threshold=threshold,
        candidate_pairs=len(candidates),
        match_rate_left=float(match_rate_left),
        weights=w,
    )
