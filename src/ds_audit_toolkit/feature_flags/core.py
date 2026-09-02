"""Flag report generator: leak_score, predictive_score, and reason per column.

Checks (Phases 5-6):
    - Adversarial validation (XGBoost train-vs-holdout classifier importance)
    - Target correlation / mutual information with the target
    - Temporal leakage (available-as-of timestamp vs target event)
    - Non-predictive: constant/near-zero-variance, duplicate columns,
      low permutation importance

Output is advisory, not an auto-drop: the analyst decides what to exclude.
"""

from typing import Any


def flag_features(df: Any, target_column: str, time_column: str | None = None) -> Any:
    """Return a per-feature flag report (leak_score, predictive_score, reason)."""
    raise NotImplementedError("flags land in Phases 5-6")
