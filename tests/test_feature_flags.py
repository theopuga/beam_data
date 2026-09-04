"""Tests for the feature audit: each check, the entry point, the report."""

import sys

import numpy as np
import pandas as pd
import pytest

from localdb.feature_flags import (
    FeatureAuditReport,
    audit_features,
    flag_adversarial_leakage,
    flag_constant_features,
    flag_duplicate_features,
    flag_target_correlation,
    flag_temporal_leakage,
)


def frame():
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "tenure_months": rng.integers(1, 60, 200).astype(float),
            "monthly_spend": rng.normal(50, 10, 200),
            "plan": rng.choice(["basic", "plus", "pro"], 200),
            "country": ["CA"] * 200,
            "spend_copy": None,  # filled below: exact copy of monthly_spend
        }
    ).assign(spend_copy=lambda d: d["monthly_spend"])


def test_flag_constant_features():
    flags = {f["feature"]: f["reason"] for f in flag_constant_features(frame())}
    assert "country" in flags  # 1 distinct value
    assert "tenure_months" not in flags and "monthly_spend" not in flags


def test_flag_near_zero_variance():
    df = pd.DataFrame({
        "wiggle": [1.0, 1.0, 1.0, 1.0 + 1e-13],  # 2 distinct values, std ~5e-14
        "normal": [1.0, 2.0, 3.0, 4.0],
    })
    flags = {f["feature"]: f["reason"] for f in flag_constant_features(df)}
    assert "wiggle" in flags and "std" in flags["wiggle"]
    assert "normal" not in flags


def test_flag_duplicate_features():
    flags = {f["feature"]: f["reason"] for f in flag_duplicate_features(frame())}
    assert flags["spend_copy"] == "identical to column 'monthly_spend'"
    assert "monthly_spend" not in flags


def test_flag_target_correlation_numeric():
    df = frame().assign(
        churn=lambda d: (d["monthly_spend"] > d["monthly_spend"].median()).astype(int),
        noise=lambda d: np.random.default_rng(1).normal(size=200))
    flags = {f["feature"] for f in flag_target_correlation(df, "churn")}
    assert "noise" not in flags  # independent of the target
    df["spend_dup_target"] = df["churn"].astype(float)
    flags = {f["feature"] for f in flag_target_correlation(df, "churn")}
    assert "spend_dup_target" in flags


def test_flag_target_correlation_categorical():
    pytest.importorskip("sklearn")
    df = frame().assign(segment=lambda d: d["plan"],  # perfect copy of the target
                        churned=lambda d: d["plan"])
    flags = {f["feature"]: f["score"] for f in flag_target_correlation(df, "churned")}
    assert flags["segment"] == pytest.approx(1.0)


def test_flag_temporal_leakage():
    df = frame().assign(
        signup_date=pd.date_range("2026-01-01", periods=200, freq="D"),
        credit_score=rng_scores(),
        credit_score_pulled_at=lambda d: d["signup_date"] + pd.Timedelta(days=1),
    )
    flags = {f["feature"]: f for f in flag_temporal_leakage(
        df, "signup_date", {"credit_score": "credit_score_pulled_at"})}
    assert flags["credit_score"]["check"] == "temporal_leakage"
    assert flags["credit_score"]["score"] == pytest.approx(1.0)

    clean = df.assign(credit_score_pulled_at=lambda d: d["signup_date"] - pd.Timedelta(days=1))
    assert flag_temporal_leakage(clean, "signup_date",
                                 {"credit_score": "credit_score_pulled_at"}) == []


def test_temporal_leakage_validates_and_skips_all_nat():
    df = frame().assign(
        signup_date=pd.date_range("2026-01-01", periods=200, freq="D"),
        credit_score=rng_scores(),
        score_ts=pd.NaT,  # availability unknown on every row -> nothing usable
    )
    with pytest.raises(KeyError, match="missing column"):
        flag_temporal_leakage(df, "signup_date", {"credit_score": "nope_ts"})
    assert flag_temporal_leakage(df, "signup_date", {"credit_score": "score_ts"}) == []


def rng_scores():
    return np.random.default_rng(3).normal(650, 50, 200)


def test_flag_adversarial_leakage():
    pytest.importorskip("xgboost")
    df = frame()
    mask = pd.Series([True] * 50 + [False] * 150)
    df["source_batch"] = np.where(mask, 1.0, 0.0)  # provenance: perfect tell
    flags = {f["feature"]: f for f in flag_adversarial_leakage(
        df, mask, n_estimators=30)}
    assert "source_batch" in flags
    assert "AUC" in flags["source_batch"]["reason"]

    iid = frame().assign(source_batch=np.random.default_rng(5).normal(size=200))
    assert flag_adversarial_leakage(iid, mask, n_estimators=30, auc_margin=0.3) == []


def test_flag_adversarial_categorical():
    pytest.importorskip("scipy")
    df = frame()
    mask = pd.Series([True] * 50 + [False] * 150)
    df["region"] = np.where(mask, "HQ", "branch")  # categorical provenance tell
    flags = {f["feature"]: f for f in flag_adversarial_leakage(df, mask, n_estimators=30)}
    assert flags["region"]["check"] == "adversarial_leakage"
    assert "cramers V" in flags["region"]["reason"]
    assert "plan" not in flags  # unrelated category: below the threshold

    masked = df.assign(region=pd.Series(["HQ", "branch"] * 100))
    assert "region" not in {f["feature"] for f in flag_adversarial_leakage(
        masked, mask, n_estimators=30, categorical_threshold=0.99)}


def test_adversarial_branches_degrade_independently(monkeypatch):
    df = frame()
    mask = pd.Series([True] * 50 + [False] * 150)
    df["region"] = np.where(mask, "HQ", "branch")      # categorical tell
    df["source_batch"] = np.where(mask, 1.0, 0.0)      # numeric tell

    monkeypatch.setitem(sys.modules, "xgboost", None)
    out = {f["feature"] for f in flag_adversarial_leakage(df, mask)}
    assert "region" in out          # categorical branch needs no xgboost
    assert "source_batch" not in out
    monkeypatch.undo()

    monkeypatch.setitem(sys.modules, "scipy.stats", None)
    out = {f["feature"] for f in flag_adversarial_leakage(df, mask, n_estimators=30)}
    assert "source_batch" in out    # numeric branch needs no scipy
    assert "region" not in out


def test_sklearn_missing_degrades(monkeypatch):
    monkeypatch.setitem(sys.modules, "sklearn.metrics", None)
    df = frame().assign(
        churn=lambda d: (d["monthly_spend"] > d["monthly_spend"].median()).astype(int))
    df["churn_copy"] = df["churn"].astype(float)
    flags = {f["feature"] for f in flag_target_correlation(df, "churn")}
    assert "churn_copy" in flags  # numeric branch unaffected
    df2 = frame().assign(churned=lambda d: d["plan"])
    assert flag_target_correlation(df2, "churned") == []  # categorical branch skipped


def test_xgboost_missing_degrades(monkeypatch):
    pytest.importorskip("xgboost")
    monkeypatch.setitem(sys.modules, "xgboost", None)
    df = frame()
    mask = pd.Series([True] * 50 + [False] * 150)
    assert flag_adversarial_leakage(df, mask) == []


def test_audit_features_progressive():
    df = frame()
    df["churned"] = (df["monthly_spend"] > 55).astype(int)
    df["spence_target_copy"] = df["churned"].astype(float)
    df["signup_date"] = pd.date_range("2026-01-01", periods=200, freq="D")
    df["score_ts"] = df["signup_date"] + pd.Timedelta(days=1)
    df["credit_score"] = rng_scores()
    mask = pd.Series([True] * 50 + [False] * 150)
    df["source_batch"] = np.where(mask, 1.0, 0.0)

    only_basics = audit_features(df)
    assert set(only_basics.flags["check"]) <= {"constant", "duplicate"}
    assert "country" in only_basics.flagged_features()

    with_target = audit_features(df, target="churned")
    assert "target_correlation" in set(with_target.flags["check"])
    assert "spence_target_copy" in with_target.flagged_features()

    with_time = audit_features(df, target="churned", time_column="signup_date",
                               available_as_of={"credit_score": "score_ts"})
    assert "temporal_leakage" in set(with_time.flags["check"])
    assert "credit_score" in with_time.flagged_features()

    with_holdout = audit_features(df, target="churned", time_column="signup_date",
                                  available_as_of={"credit_score": "score_ts"},
                                  holdout_mask=mask)
    assert "adversarial_leakage" in set(with_holdout.flags["check"])
    assert "churned" not in with_holdout.flagged_features()
    assert "score_ts" not in with_holdout.flagged_features()


def test_audit_features_validates_args():
    df = frame()
    with pytest.raises(KeyError, match="target"):
        audit_features(df, target="nope")
    with pytest.raises(ValueError, match="time_column"):
        audit_features(df, available_as_of={"a": "b"})
    with pytest.raises(ValueError, match="align"):
        audit_features(df, holdout_mask=pd.Series([True] * 3))


def test_report_summary_flagged_and_save(tmp_path):
    report = audit_features(frame(), target=None)
    summary = report.summary()
    assert list(summary.columns) == ["feature", "checks", "reasons", "max_score"]
    assert report.flagged_features() == sorted(report.flagged_features())
    assert (summary["reasons"].str.len() > 0).all()
    assert ((summary["max_score"] >= 0) & (summary["max_score"] <= 1)).all()

    empty = FeatureAuditReport()
    assert empty.summary().empty and empty.flagged_features() == []

    out = report.save(tmp_path / "reports" / "feature_flags.csv")
    saved = pd.read_csv(out)
    assert list(saved.columns) == ["feature", "check", "score", "reason"]
    assert len(saved) == len(report.flags)
