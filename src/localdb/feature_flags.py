"""Pre-model feature audit: flag features before they go into a model.

The workflow for downloaded data feeding a model (e.g. XGBoost):
    1. non-predictive checks: constant/near-zero-variance columns, exact
       duplicate columns
    2. target checks: correlation with the target (Pearson for numeric
       pairs, normalized mutual information for categorical pairs)
    3. leakage checks: temporal (feature timestamp after the event it
       predicts) and adversarial (train/holdout rows distinguishable)

Report, not auto-drop: every flag carries a score and a reason — the
analyst decides. Optional dependencies degrade gracefully: without xgboost
the adversarial check returns no flags; without scikit-learn the
categorical branch of the target-correlation check returns no flags.

audit_features(df) runs whatever checks the arguments allow: pass just a
frame for the non-predictive checks; add target=, time_column=/
available_as_of=, or holdout_mask= to unlock the rest.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

_DEFAULT_CORR_THRESHOLD = 0.95
_DEFAULT_LEAK_SHARE_THRESHOLD = 0.0
_DEFAULT_ADVERSARIAL_AUC_MARGIN = 0.05
_DEFAULT_ADVERSARIAL_IMPORTANCE_THRESHOLD = 0.05
_DEFAULT_CONSTANT_MAX_UNIQUE = 1
_DEFAULT_CONSTANT_NEAR_ZERO_STD = 1e-12

_FLAG_COLUMNS = ["feature", "check", "score", "reason"]


@dataclass
class FeatureAuditReport:
    """Advisory feature flags — evidence for the analyst, not a gate."""

    flags: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=_FLAG_COLUMNS))

    def summary(self) -> pd.DataFrame:
        """One row per flagged feature; per-check reasons collapsed."""
        if self.flags.empty:
            return pd.DataFrame(columns=["feature", "checks", "reasons", "max_score"])
        grouped = self.flags.groupby("feature", sort=True)
        return pd.DataFrame(
            {
                "checks": grouped["check"].apply(lambda s: ", ".join(sorted(s))),
                "reasons": grouped["reason"].apply("; ".join),
                "max_score": grouped["score"].max(),
            }
        ).reset_index()

    def flagged_features(self) -> list[str]:
        """Names of all flagged features."""
        return sorted(self.flags["feature"].unique()) if not self.flags.empty else []

    def save(self, path: str | Path) -> Path:
        """Write the flag table to CSV (parent dirs created)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.flags.to_csv(p, index=False)
        return p


def _new_flags(feature: str, check: str, score: float, reason: str) -> dict:
    return {"feature": feature, "check": check, "score": float(score), "reason": reason}


def _numeric_columns(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    return [
        c for c in df.columns
        if c not in exclude and pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_bool_dtype(df[c])
    ]


def _categorical_columns(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    out = []
    for c in df.columns:
        if c in exclude:
            continue
        numeric = pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])
        datetime = pd.api.types.is_datetime64_any_dtype(df[c])
        if not numeric and not datetime:
            out.append(c)
    return out


def flag_constant_features(df: pd.DataFrame, exclude: set[str] | None = None,
                           max_unique: int = _DEFAULT_CONSTANT_MAX_UNIQUE,
                           near_zero_std: float = _DEFAULT_CONSTANT_NEAR_ZERO_STD,
                           ) -> list[dict]:
    """Columns with (near) no variation: a single distinct value, or a
    numeric column whose standard deviation is under near_zero_std."""
    exclude = exclude or set()
    flags = []
    for col in _categorical_columns(df, exclude) + _numeric_columns(df, exclude):
        s = df[col].dropna()
        n_unique = int(s.nunique())
        if n_unique <= max_unique:
            flags.append(_new_flags(col, "constant", n_unique,
                                    f"{n_unique} distinct value(s) across {len(s)} non-null rows"))
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            std = float(pd.to_numeric(s, errors="coerce").std())
            if not np.isnan(std) and std < near_zero_std:
                flags.append(_new_flags(
                    col, "constant", std,
                    f"numeric std {std:.2e} below near_zero_std={near_zero_std:.0e}"))
    return flags


def _column_key(df: pd.DataFrame, col: str) -> bytes:
    return pd.util.hash_pandas_object(df[col], index=False).to_numpy().tobytes()


def flag_duplicate_features(df: pd.DataFrame, exclude: set[str] | None = None) -> list[dict]:
    """Columns exactly equal to an earlier column (copy-paste / re-derived)."""
    exclude = exclude or set()
    first_with_key: dict[bytes, str] = {}
    flags = []
    for col in df.columns:
        if col in exclude:
            continue
        key = _column_key(df, col)
        original = first_with_key.setdefault(key, col)
        if original != col:
            flags.append(_new_flags(col, "duplicate", 1.0, f"identical to column {original!r}"))
    return flags


def flag_target_correlation(df: pd.DataFrame, target: str,
                            threshold: float = _DEFAULT_CORR_THRESHOLD,
                            ) -> list[dict]:
    """Columns tracking the target too closely: |Pearson| for numeric
    pairs, normalized mutual information for categorical pairs (needs
    scikit-learn; without it the categorical branch returns no flags)."""
    flags = []
    numeric = [c for c in _numeric_columns(df, {target}) if c != target]
    categoricals = [c for c in _categorical_columns(df, {target}) if c != target]
    if pd.api.types.is_numeric_dtype(df[target]):
        for col in numeric:
            corr = df[col].corr(df[target])
            if not np.isnan(corr) and abs(corr) >= threshold:
                flags.append(_new_flags(
                    col, "target_correlation", abs(corr),
                    f"|pearson| = {abs(corr):.3f} >= {threshold}"))
    if categoricals:
        try:
            from sklearn.metrics import normalized_mutual_info_score
        except ImportError:
            return flags
        t = df[target].fillna("__missing__").astype(str)
        for col in categoricals:
            nmi = normalized_mutual_info_score(df[col].fillna("__missing__").astype(str), t)
            if nmi >= threshold:
                flags.append(_new_flags(
                    col, "target_correlation", nmi,
                    f"normalized MI = {nmi:.3f} >= {threshold}"))
    return flags


def flag_temporal_leakage(df: pd.DataFrame, time_column: str,
                          available_as_of: dict[str, str],
                          max_leak_share: float = _DEFAULT_LEAK_SHARE_THRESHOLD,
                          ) -> list[dict]:
    """Features whose availability timestamp is after the event time.

    available_as_of maps feature -> column holding when that feature's
    value became known. Rows with availability after time_column cannot
    legally use the feature; the flag score is the leaked-row share.
    """
    event = pd.to_datetime(df[time_column], errors="coerce")
    flags = []
    for feature, ts_col in available_as_of.items():
        if feature not in df.columns or ts_col not in df.columns:
            raise KeyError(
                f"available_as_of references missing column(s): "
                f"{[c for c in (feature, ts_col) if c not in df.columns]}")
        available = pd.to_datetime(df[ts_col], errors="coerce")
        usable = event.notna() & available.notna()
        if not usable.any():
            continue
        leaked = int((available[usable] > event[usable]).sum())
        share = leaked / int(usable.sum())
        if share > max_leak_share:
            flags.append(_new_flags(
                feature, "temporal_leakage", share,
                f"{leaked}/{int(usable.sum())} rows ({share:.1%}) have "
                f"{ts_col!r} after the {time_column!r} event"))
    return flags


def flag_adversarial_leakage(df: pd.DataFrame, holdout_mask: pd.Series,
                             exclude: set[str] | None = None,
                             auc_margin: float = _DEFAULT_ADVERSARIAL_AUC_MARGIN,
                             importance_threshold: float = _DEFAULT_ADVERSARIAL_IMPORTANCE_THRESHOLD,
                             n_estimators: int = 100,
                             random_state: int = 0,
                             ) -> list[dict]:
    """Features that let a classifier tell train rows from holdout rows.

    Trains XGBoost to predict the holdout mask from the numeric features.
    If the out-of-sample AUC is within auc_margin of 0.5, train and holdout
    are indistinguishable and nothing is flagged; otherwise features whose
    gain importance share exceeds importance_threshold are flagged.
    Without xgboost installed this returns no flags (graceful degradation).
    """
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return []
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split

    exclude = (exclude or set()) | {"__holdout__"}
    features = _numeric_columns(df, exclude)
    X = df[features].select_dtypes(include=[np.number])
    y = holdout_mask.astype(int).to_numpy()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=random_state, stratify=y)
    model = XGBClassifier(
        n_estimators=n_estimators, max_depth=3, learning_rate=0.1,
        eval_metric="logloss", verbosity=0, random_state=random_state)
    model.fit(X_train, y_train)
    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    if auc <= 0.5 + auc_margin:
        return []
    importances = pd.Series(model.get_booster().get_score(importance_type="gain"))
    importances = importances / importances.sum()
    flags = []
    for feature, importance in importances.items():
        if importance >= importance_threshold:
            flags.append(_new_flags(
                feature, "adversarial_leakage", importance,
                f"train/holdout AUC {auc:.3f}; gain share {importance:.3f} "
                f">= {importance_threshold}"))
    return flags


def audit_features(df: pd.DataFrame, target: str | None = None,
                   time_column: str | None = None,
                   available_as_of: dict[str, str] | None = None,
                   holdout_mask: pd.Series | None = None,
                   corr_threshold: float = _DEFAULT_CORR_THRESHOLD,
                   max_leak_share: float = _DEFAULT_LEAK_SHARE_THRESHOLD,
                   adversarial_auc_margin: float = _DEFAULT_ADVERSARIAL_AUC_MARGIN,
                   adversarial_importance_threshold: float = _DEFAULT_ADVERSARIAL_IMPORTANCE_THRESHOLD,
                   max_unique: int = _DEFAULT_CONSTANT_MAX_UNIQUE,
                   near_zero_std: float = _DEFAULT_CONSTANT_NEAR_ZERO_STD,
                   ) -> FeatureAuditReport:
    """Run the feature checks the arguments allow and return the report.

    Args:
        target: column to correlate features against (unlocks the
            target-correlation check).
        time_column: event timestamp column, used with available_as_of
            (unlocks the temporal-leakage check).
        available_as_of: feature -> availability-timestamp column.
        holdout_mask: boolean Series marking holdout rows (unlocks the
            adversarial check).
        Thresholds: corr_threshold, max_leak_share,
            adversarial_auc_margin, adversarial_importance_threshold,
            max_unique, near_zero_std — all tunable, see the flag functions.
    """
    reserved = {c for c in (target, time_column) if c}
    if available_as_of:
        reserved |= set(available_as_of.values())

    flags: list[dict] = []
    flags += flag_constant_features(df, exclude=reserved, max_unique=max_unique,
                                    near_zero_std=near_zero_std)
    flags += flag_duplicate_features(df, exclude=reserved)
    if target is not None:
        if target not in df.columns:
            raise KeyError(f"target column {target!r} not in frame")
        flags += flag_target_correlation(df, target, threshold=corr_threshold)
    if available_as_of is not None:
        if time_column is None:
            raise ValueError("available_as_of needs time_column= to compare against")
        flags += flag_temporal_leakage(df, time_column, available_as_of,
                                       max_leak_share=max_leak_share)
    if holdout_mask is not None:
        if len(holdout_mask) != len(df):
            raise ValueError("holdout_mask must align with the frame's rows")
        flags += flag_adversarial_leakage(
            df, holdout_mask, exclude=reserved,
            auc_margin=adversarial_auc_margin,
            importance_threshold=adversarial_importance_threshold)
    return FeatureAuditReport(flags=pd.DataFrame(flags, columns=_FLAG_COLUMNS))
