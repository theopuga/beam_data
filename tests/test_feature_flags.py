"""Tests for feature flagging (Phases 5-6): leak scores, predictive scores, reasons."""

import numpy as np
import pandas as pd
import pytest

from ds_audit_toolkit.feature_flags import flag_features

N = 240


def entries_by_column(report):
    return {entry.column: entry for entry in report.flags}


def test_copy_of_target_gets_perfect_leak_score():
    rng = np.random.RandomState(42)
    y = rng.binomial(1, 0.5, N).astype(float)
    df = pd.DataFrame({"y": y, "leak": y, "noise": rng.normal(size=N)})
    report = flag_features(df, "y")
    leak = entries_by_column(report)["leak"]
    assert leak.leak_score == 1.0
    assert "near-perfect correlation" in leak.reason
    assert "r=" in leak.reason
    assert report.target_column == "y"


def test_constant_column_is_non_predictive():
    rng = np.random.RandomState(42)
    df = pd.DataFrame(
        {
            "y": rng.binomial(1, 0.5, N).astype(float),
            "const": np.ones(N),
            "noise": rng.normal(size=N),
        }
    )
    report = flag_features(df, "y")
    const = entries_by_column(report)["const"]
    assert const.predictive_score == 0.0
    assert "constant" in const.reason
    assert const.leak_score == 0.0


def test_duplicate_column_reports_original():
    rng = np.random.RandomState(42)
    base = rng.normal(size=N)
    df = pd.DataFrame(
        {
            "y": rng.binomial(1, 0.5, N).astype(float),
            "base": base,
            "copy": base,
            "noise": rng.normal(size=N),
        }
    )
    report = flag_features(df, "y")
    columns = entries_by_column(report)
    assert "duplicate of 'base'" in columns["copy"].reason
    assert "duplicate" not in columns["base"].reason


def test_distribution_shift_dominates_adversarial_validation():
    rng = np.random.RandomState(42)
    shift = rng.normal(size=N)
    shift[N // 2 :] += 3.0
    df = pd.DataFrame(
        {
            "y": rng.binomial(1, 0.5, N).astype(float),
            "shift": shift,
            "noise": rng.normal(size=N),
        }
    )
    report = flag_features(df, "y")
    columns = entries_by_column(report)
    assert columns["shift"].leak_score == pytest.approx(1.0)
    assert "adversarial" in columns["shift"].reason
    assert "provenance" in columns["shift"].reason
    assert columns["shift"].leak_score > columns["noise"].leak_score


def test_as_of_after_target_event_flags_temporal_leak():
    rng = np.random.RandomState(42)
    times = pd.date_range("2024-01-01", periods=N, freq="h")
    offsets = pd.to_timedelta(rng.normal(0, 6 * 3600, N).astype("int64"), unit="s")
    df = pd.DataFrame(
        {
            "y": rng.binomial(1, 0.5, N).astype(float),
            "time": times,
            "signal": rng.normal(size=N),
            "signal__as_of": times + offsets,
        }
    )
    report = flag_features(df, "y", time_column="time")
    signal = entries_by_column(report)["signal"]
    assert signal.leak_score == 1.0
    assert "after the target event" in signal.reason


def test_benign_random_column_is_clean_but_reported():
    rng = np.random.RandomState(42)
    df = pd.DataFrame(
        {
            "y": rng.binomial(1, 0.5, N).astype(float),
            "benign": rng.normal(size=N),
            "benign2": rng.normal(size=N),
        }
    )
    report = flag_features(df, "y")
    benign = entries_by_column(report)["benign"]
    assert benign.leak_score == 0.0
    assert benign.reason == ""
    assert 0.0 <= benign.predictive_score <= 1.0


def test_target_and_time_columns_are_excluded_from_flags():
    rng = np.random.RandomState(42)
    df = pd.DataFrame(
        {
            "y": rng.binomial(1, 0.5, N).astype(float),
            "time": pd.date_range("2024-01-01", periods=N, freq="h"),
            "a": rng.normal(size=N),
            "b": rng.normal(size=N),
        }
    )
    report = flag_features(df, "y", time_column="time")
    assert report.target_column == "y"
    assert {entry.column for entry in report.flags} == {"a", "b"}


def test_tiny_frame_skips_model_checks():
    df = pd.DataFrame({"y": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0], "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    report = flag_features(df, "y")
    x = entries_by_column(report)["x"]
    assert x.predictive_score == 0.0
    assert x.leak_score == 0.0
    assert "skipped" in x.reason


def test_all_nan_column_is_constant():
    rng = np.random.RandomState(42)
    df = pd.DataFrame(
        {
            "y": rng.binomial(1, 0.5, N).astype(float),
            "empty": pd.Series(np.nan, index=range(N)),
            "noise": rng.normal(size=N),
        }
    )
    report = flag_features(df, "y")
    empty = entries_by_column(report)["empty"]
    assert empty.predictive_score == 0.0
    assert "constant" in empty.reason
    assert empty.leak_score == 0.0


def test_categorical_target_uses_mutual_information():
    rng = np.random.RandomState(42)
    y = rng.choice(["a", "b"], N)
    df = pd.DataFrame({"y": y, "leak": y, "color": rng.choice(["red", "green", "blue"], N)})
    report = flag_features(df, "y")
    leak = entries_by_column(report)["leak"]
    assert leak.leak_score == 1.0
    assert "mutual information" in leak.reason


def test_missing_target_column_raises():
    df = pd.DataFrame({"a": [1.0, 2.0]})
    with pytest.raises(ValueError, match="target column"):
        flag_features(df, "y")
