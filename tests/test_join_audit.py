"""Tests for the join audit: key quality gate + datacompy exact match."""

import pandas as pd
import pytest

from ds_audit_toolkit.join_audit import audit_join, check_key_quality


def make_frames():
    left = pd.DataFrame({"id": ["a", "b", "c", "d"], "amt": [1.0, 2.0, 3.0, 4.0]})
    right = pd.DataFrame({"id": ["a", "b", "c", "e"], "amt": [1.0, 2.0, 3.0, 9.0]})
    return left, right


def test_check_key_quality_counts():
    left, right = make_frames()
    report = check_key_quality(left, right, "id")
    assert report.duplicates == {"left": 0, "right": 0}
    assert report.nulls == {"left": 0, "right": 0}
    assert report.dtype_mismatches == []


def test_check_key_quality_findings():
    left = pd.DataFrame({"id": ["a", "a", None], "v": [1, 2, 3]})
    right = pd.DataFrame({"id": [1, 2], "v": [1, 2]})
    report = check_key_quality(left, right, "id")
    assert report.duplicates == {"left": 1, "right": 0}
    assert report.nulls == {"left": 1, "right": 0}
    assert report.dtype_mismatches and "object" in report.dtype_mismatches[0]
    assert "int64" in report.dtype_mismatches[0]


def test_check_key_quality_missing_key_raises():
    left = pd.DataFrame({"k": [1]})
    right = pd.DataFrame({"id": [1]})
    with pytest.raises(ValueError, match="missing key column 'id'"):
        check_key_quality(left, right, "id")


def test_audit_join_perfect_match():
    df = pd.DataFrame({"id": ["a", "b"], "amt": [1.0, 2.0]})
    result = audit_join(df, df.copy(), "id", fuzzy_fallback=False)
    assert result.match_rate == 1.0
    assert result.matched_rows == 2
    assert result.unmatched_keys == []
    assert result.column_mismatch_rates == {}
    assert result.fuzzy_used is False
    assert result.datacompy_report is not None


def test_audit_join_partial_match():
    left, right = make_frames()
    result = audit_join(left, right, "id", fuzzy_fallback=False)
    assert result.match_rate == pytest.approx(0.75)
    assert result.matched_rows == 3
    assert set(result.unmatched_keys) == {"d", "e"}


def test_audit_join_column_mismatch_rate():
    left, right = make_frames()
    right.loc[2, "amt"] = 30.0
    result = audit_join(left, right, "id", fuzzy_fallback=False)
    assert result.column_mismatch_rates["amt"] == pytest.approx(1 / 3)


def test_audit_join_abs_tolerance_absorbs_rounding():
    left = pd.DataFrame({"id": ["a", "b"], "amt": [1.0, 2.0]})
    right = pd.DataFrame({"id": ["a", "b"], "amt": [1.001, 2.0]})
    strict = audit_join(left, right, "id", fuzzy_fallback=False)
    assert strict.column_mismatch_rates["amt"] == pytest.approx(0.5)
    tolerant = audit_join(left, right, "id", fuzzy_fallback=False, abs_tol=0.01)
    assert tolerant.column_mismatch_rates == {}


def test_audit_join_per_column_tolerance():
    left = pd.DataFrame({"id": ["a"], "amt": [1.0], "qty": [5.0]})
    right = pd.DataFrame({"id": ["a"], "amt": [1.001], "qty": [9.0]})
    result = audit_join(
        left, right, "id", fuzzy_fallback=False, abs_tol={"amt": 0.01}
    )
    assert "amt" not in result.column_mismatch_rates
    assert result.column_mismatch_rates["qty"] == pytest.approx(1.0)


def test_audit_join_duplicate_keys_raise():
    left = pd.DataFrame({"id": ["a", "a"], "v": [1, 2]})
    right = pd.DataFrame({"id": ["a"], "v": [1]})
    with pytest.raises(ValueError, match="dedupe"):
        audit_join(left, right, "id")


def test_audit_join_below_threshold_triggers_fuzzy():
    left, right = make_frames()
    with pytest.raises(NotImplementedError, match="Phase 3"):
        audit_join(left, right, "id")


def test_audit_join_below_threshold_without_fuzzy_returns_report():
    left, right = make_frames()
    result = audit_join(left, right, "id", fuzzy_fallback=False)
    assert result.match_rate < result.match_threshold
    assert result.match_threshold == 0.95
