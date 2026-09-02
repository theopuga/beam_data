"""Match report (exact via datacompy) + fuzzy fallback (recordlinkage/Splink)."""

from typing import Any


def check_key_quality(left: Any, right: Any, key: str) -> dict:
    """Pre-join checks: duplicate keys, null keys, dtype mismatches between sides.

    Dtype mismatches between sides are a common silent cause of false non-matches.
    """
    raise NotImplementedError("key quality checks land in Phase 2")


def audit_join(left: Any, right: Any, key: str, match_threshold: float = 0.95,
               fuzzy_fallback: bool = True) -> dict:
    """Join two datasets and audit match quality.

    Uses datacompy for the exact-match report (row counts, unmatched keys,
    column-level mismatch rates, dtype mismatches). If the match rate falls
    below `match_threshold` and `fuzzy_fallback` is set, triggers a fuzzy pass
    and reports match confidence instead of a binary yes/no.
    """
    raise NotImplementedError("exact-match audit lands in Phase 2; fuzzy in Phase 3")
