"""Flag report generator: leak_score, predictive_score, and reason per column.

Checks (Phases 5-6):
    - Non-predictive: constant / near-zero-variance columns (predictive_score
      forced to 0.0) and exact duplicates of an earlier column.
    - Target correlation: numeric features with |pearson r| >= 0.95 vs the
      target score leak_score 1.0; object/category features are scored with
      discrete mutual information normalized by the target entropy (capped
      at 1.0) and flagged at >= 0.8.
    - predictive_score: small deterministic XGBoost classifier + permutation
      importance (n_repeats=3), normalized to 0-1 by the max.
    - Adversarial validation: rows are labeled 0/1 by half (sorted by the
      time column when one is set, else positional halves) and XGBoost
      classifies row provenance; contributions only count when the classifier
      actually separates the halves (cross-validated AUC >= 0.6 — a chance
      classifier encodes noise, not provenance). Features with normalized
      gain importance >= 0.15 contribute that value to leak_score.
    - Temporal leakage: when a time column is set, a feature with a
      "<feature>__as_of" timestamp column holding any value after the target
      event scores leak_score 1.0.

Output is advisory, not an auto-drop: the analyst decides what to exclude.
Determinism: fixed seeds everywhere, n_jobs=1, stable mergesort for the
time-ordered split. Non-numeric targets are mapped to codes; all-NaN columns
and tiny frames (< 20 rows, model-based checks skipped and noted) handled.
"""

import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import entropy
from sklearn.feature_selection import mutual_info_classif
from sklearn.inspection import permutation_importance
from sklearn.model_selection import StratifiedKFold, cross_val_score
from xgboost import XGBClassifier
from xgboost.core import XGBoostError

from ds_audit_toolkit.types import FeatureFlagReport, FlagEntry

_CORRELATION_THRESHOLD = 0.95
_MUTUAL_INFORMATION_THRESHOLD = 0.8
_ADVERSARIAL_IMPORTANCE_THRESHOLD = 0.15
_ADVERSARIAL_AUC_GATE = 0.6
_NEAR_ZERO_DOMINANT_FRACTION = 0.98
_MIN_ROWS_FOR_MODELS = 20
_PERMUTATION_REPEATS = 3
_ADVERSARIAL_FOLDS = 3
_MODEL_ERRORS = (XGBoostError, ValueError, TypeError)


def _make_model() -> XGBClassifier:
    """Small deterministic classifier shared by predictive and adversarial fits."""
    return XGBClassifier(
        n_estimators=100,
        max_depth=3,
        random_state=0,
        n_jobs=1,
        eval_metric="logloss",
        verbosity=0,
        importance_type="gain",
    )


def _target_values(series: pd.Series) -> pd.Series:
    """Target as float: numeric dtypes pass through, everything else maps to codes."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    values = pd.factorize(series)[0].astype(float)
    values[values < 0] = np.nan
    return pd.Series(values, index=series.index)


def _factorize(series: pd.Series) -> np.ndarray:
    """Integer codes per distinct value (-1 for missing); string fallback for unhashables."""
    try:
        return pd.factorize(series)[0]
    except (TypeError, ValueError):
        return pd.factorize(series.astype(str))[0]


def _encode_features(
    df: pd.DataFrame, columns: list[str]
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Float feature matrix plus integer codes for object/category columns.

    Datetimes become epoch values so models can use them; missing values stay
    NaN (XGBoost treats them as missing) and infinities become NaN so XGBoost
    never sees them. The codes dict (NaN -> -1) is reused by the
    mutual-information check; unhashable object cells fall back to their
    string form so encoding never raises.
    """
    encoded = pd.DataFrame(index=df.index)
    categorical_codes: dict[str, np.ndarray] = {}
    for column in columns:
        series = df[column]
        if (
            pd.api.types.is_datetime64_any_dtype(series)
            or pd.api.types.is_timedelta64_dtype(series)
        ):
            values = pd.to_numeric(series, errors="coerce").astype(float)
            values[series.isna()] = np.nan
        elif pd.api.types.is_object_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype):
            codes = _factorize(series)
            categorical_codes[column] = codes
            values = pd.Series(codes.astype(float), index=series.index)
            values[series.isna()] = np.nan
        else:
            values = pd.to_numeric(series, errors="coerce").astype(float)
        encoded[column] = values.replace([np.inf, -np.inf], np.nan)
    return encoded, categorical_codes


def _column_key(series: pd.Series) -> tuple | None:
    """Hashable value tuple for duplicate detection (NaN normalized); None if unhashable."""
    try:
        key = tuple("__nan__" if pd.isna(value) else value for value in series.tolist())
        hash(key)
        return key
    except (TypeError, ValueError):
        return None


def _non_predictive_reason(series: pd.Series) -> str | None:
    """Constant / near-zero-variance verdict for one column, None when informative."""
    if series.isna().all():
        return "constant column (all NaN)"
    if series.nunique(dropna=False) <= 1:
        return "constant column (single value)"
    if pd.api.types.is_numeric_dtype(series):
        observed = series.dropna()
        if len(observed) <= 1 or float(observed.std()) == 0.0:
            return "near-zero-variance (one observed value)"
    try:
        counts = series.value_counts(normalize=True, dropna=False)
        dominant = float(counts.iloc[0]) if len(counts) else 0.0
    except (TypeError, ValueError):
        return None
    if dominant >= _NEAR_ZERO_DOMINANT_FRACTION:
        return f"near-zero-variance ({dominant:.0%} of rows share one value)"
    return None


def _find_duplicates(df: pd.DataFrame, columns: list[str]) -> dict[str, str]:
    """Map each column to the first earlier column with identical values."""
    seen: dict[tuple, str] = {}
    duplicates: dict[str, str] = {}
    for column in columns:
        key = _column_key(df[column])
        if key is None:
            continue
        if key in seen:
            duplicates[column] = seen[key]
        else:
            seen[key] = column
    return duplicates


def _adversarial_labels(df: pd.DataFrame, time_column: str | None) -> pd.Series:
    """0/1 half-membership labels: first half vs second half of the frame.

    Rows are ordered by the time column (stable sort) when one is set, so the
    split separates early from late rows; otherwise the positional halves are
    used. Unsortable time values fall back to the positional split.
    """
    n = len(df)
    values = np.ones(n, dtype=int)
    split = n // 2
    if split:
        positions = np.arange(n)
        if time_column is not None:
            try:
                positions = np.argsort(df[time_column].to_numpy(), kind="stable")
            except TypeError:
                positions = np.arange(n)
        values[positions[:split]] = 0
    return pd.Series(values, index=df.index)


def _add_correlation_flags(
    df: pd.DataFrame,
    features: list[str],
    target: pd.Series,
    leak: dict[str, float],
    reasons: dict[str, list[str]],
    threshold: float,
) -> None:
    """Flag numeric features whose |pearson r| vs the target reaches `threshold`."""
    for column in features:
        if not pd.api.types.is_numeric_dtype(df[column]):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                corr = float(df[column].corr(target))
        except (TypeError, ValueError):
            continue
        if np.isnan(corr):
            continue
        if abs(corr) >= threshold:
            leak[column] = max(leak[column], 1.0)
            reasons[column].append(f"near-perfect correlation with target (r={corr:.3f})")


def _add_mutual_information_flags(
    target_series: pd.Series,
    categorical_codes: dict[str, np.ndarray],
    leak: dict[str, float],
    reasons: dict[str, list[str]],
    threshold: float,
) -> None:
    """Flag object/category features whose MI (normalized by target entropy) is high.

    MI and the target entropy are both in nats, so the ratio sits in 0-1
    (capped); a feature that reproduces the target reaches 1.0. Rows with a
    missing feature code or target are dropped from the contingency.
    """
    if not categorical_codes:
        return
    labels = pd.factorize(target_series)[0]
    counts = np.bincount(labels[labels >= 0])
    if not counts.size or counts.sum() == 0:
        return
    target_entropy = float(entropy(counts))
    if target_entropy <= 0.0:
        return
    for column, codes in categorical_codes.items():
        mask = (codes >= 0) & (labels >= 0)
        if int(mask.sum()) < 2:
            continue
        try:
            mi = mutual_info_classif(
                codes[mask].reshape(-1, 1),
                labels[mask],
                discrete_features=True,
                random_state=0,
            )[0]
        except (TypeError, ValueError):
            continue
        normalized = float(min(mi / target_entropy, 1.0))
        if normalized >= threshold:
            leak[column] = max(leak[column], 1.0)
            reasons[column].append(
                f"high mutual information with target (normalized MI={normalized:.2f})"
            )


def _add_predictive_scores(
    encoded: pd.DataFrame, target: pd.Series, predictive: dict[str, float]
) -> None:
    """Permutation importance of a small deterministic model, normalized 0-1 by max."""
    mask = target.notna().to_numpy()
    y = target[mask].to_numpy()
    if len(y) == 0 or pd.Series(y).nunique() < 2:
        return
    X = encoded[mask]
    if X.shape[1] == 0:
        return
    try:
        model = _make_model()
        model.fit(X, y)
        importance = permutation_importance(
            model, X, y, n_repeats=_PERMUTATION_REPEATS, random_state=0, n_jobs=1
        )
    except _MODEL_ERRORS:
        return
    scores = np.clip(np.asarray(importance.importances_mean, dtype=float), 0.0, None)
    peak = float(scores.max()) if scores.size else 0.0
    if peak <= 0.0:
        return
    for column, score in zip(encoded.columns, scores, strict=True):
        predictive[column] = max(predictive[column], min(float(score) / peak, 1.0))


def _add_adversarial_flags(
    df: pd.DataFrame,
    encoded: pd.DataFrame,
    time_column: str | None,
    leak: dict[str, float],
    reasons: dict[str, list[str]],
    importance_threshold: float,
    auc_gate: float,
) -> None:
    """Flag features that encode which half a row comes from.

    The half classifier only contributes when it genuinely separates the
    halves (cross-validated AUC >= `auc_gate`): at chance level the importances
    are noise and would flag innocent columns. Importances are gain-based and
    normalized to 0-1 by the max; features at or above `importance_threshold`
    contribute their normalized value to leak_score.
    """
    if encoded.shape[1] == 0:
        return
    labels = _adversarial_labels(df, time_column)
    y = labels.to_numpy()
    if np.unique(y).size < 2:
        return
    fold_count = int(min(_ADVERSARIAL_FOLDS, np.bincount(y).min()))
    if fold_count < 2:
        return
    try:
        auc = cross_val_score(
            _make_model(),
            encoded,
            y,
            cv=StratifiedKFold(n_splits=fold_count, shuffle=True, random_state=0),
            scoring="roc_auc",
        )
    except _MODEL_ERRORS:
        return
    if len(auc) == 0 or float(np.mean(auc)) < auc_gate:
        return
    try:
        model = _make_model()
        model.fit(encoded, y)
        gains = np.asarray(model.feature_importances_, dtype=float)
    except _MODEL_ERRORS:
        return
    if gains.size != encoded.shape[1]:
        return
    peak = float(gains.max())
    if peak <= 0.0:
        return
    for column, gain in zip(encoded.columns, gains, strict=True):
        normalized = min(float(gain) / peak, 1.0)
        if normalized >= importance_threshold:
            leak[column] = max(leak[column], normalized)
            reasons[column].append(
                "adversarial validation: high importance encoding row provenance "
                f"(normalized gain={normalized:.2f})"
            )


def _add_temporal_flags(
    df: pd.DataFrame,
    features: list[str],
    time_column: str,
    leak: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    """Flag features whose "<feature>__as_of" timestamps pass the target event."""
    try:
        event_time = pd.to_datetime(df[time_column], errors="coerce")
    except (TypeError, ValueError):
        return
    for column in features:
        as_of_column = f"{column}__as_of"
        if as_of_column not in df.columns:
            continue
        try:
            as_of = pd.to_datetime(df[as_of_column], errors="coerce")
            delayed = bool((as_of > event_time).any())
        except (TypeError, ValueError):
            continue
        if delayed:
            leak[column] = max(leak[column], 1.0)
            reasons[column].append(
                "feature values available after the target event (as-of timestamp)"
            )


def flag_features(
    df: Any,
    target_column: str,
    time_column: str | None = None,
    *,
    correlation_threshold: float = _CORRELATION_THRESHOLD,
    mutual_information_threshold: float = _MUTUAL_INFORMATION_THRESHOLD,
    adversarial_importance_threshold: float = _ADVERSARIAL_IMPORTANCE_THRESHOLD,
    adversarial_auc_gate: float = _ADVERSARIAL_AUC_GATE,
    min_rows_for_models: int = _MIN_ROWS_FOR_MODELS,
) -> FeatureFlagReport:
    """Return a per-feature flag report (leak_score, predictive_score, reason).

    Every column except the target and the time column gets one advisory
    FlagEntry: leak_score is the max of the triggered leak contributions
    (0.0-1.0) and reason joins the triggered checks with "; " (empty when
    clean). Model-based checks (permutation importance, mutual information,
    adversarial validation) are skipped for frames smaller than
    `min_rows_for_models` and noted in the reason; the thresholds are keyword
    arguments so analysts can tighten or relax the defaults.
    """
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    if target_column not in df.columns:
        raise ValueError(f"target column {target_column!r} not found in frame")
    if time_column is not None and time_column not in df.columns:
        raise ValueError(f"time column {time_column!r} not found in frame")

    features = [column for column in df.columns if column not in (target_column, time_column)]
    tiny = len(df) < min_rows_for_models
    target = _target_values(df[target_column])
    encoded, categorical_codes = _encode_features(df, features)

    reasons: dict[str, list[str]] = {column: [] for column in features}
    leak: dict[str, float] = {column: 0.0 for column in features}
    predictive: dict[str, float] = {column: 0.0 for column in features}

    non_predictive: dict[str, str] = {}
    for column in features:
        reason = _non_predictive_reason(df[column])
        if reason is not None:
            non_predictive[column] = reason
            reasons[column].append(reason)
    for column, original in _find_duplicates(df, features).items():
        reasons[column].append(f"duplicate of {original!r}")

    _add_correlation_flags(df, features, target, leak, reasons, correlation_threshold)

    if not tiny:
        _add_mutual_information_flags(
            df[target_column], categorical_codes, leak, reasons, mutual_information_threshold
        )
        _add_predictive_scores(encoded, target, predictive)
        _add_adversarial_flags(
            df,
            encoded,
            time_column,
            leak,
            reasons,
            adversarial_importance_threshold,
            adversarial_auc_gate,
        )

    if time_column is not None:
        _add_temporal_flags(df, features, time_column, leak, reasons)

    if tiny:
        for column in features:
            reasons[column].append(
                f"frame too small ({len(df)} rows < {min_rows_for_models}); "
                "model-based checks skipped"
            )
    for column in non_predictive:
        predictive[column] = 0.0

    flags = [
        FlagEntry(
            column=column,
            leak_score=float(min(max(leak[column], 0.0), 1.0)),
            predictive_score=float(min(max(predictive[column], 0.0), 1.0)),
            reason="; ".join(reasons[column]),
        )
        for column in features
    ]
    return FeatureFlagReport(target_column=target_column, flags=flags)
