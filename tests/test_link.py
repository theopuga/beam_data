"""Tests for linking tables on identifiers."""

import pandas as pd
import pytest

from localdb import Tables, link_tables


def clients():
    return pd.DataFrame({
        "client_id": ["A1", "B2", "C3", "D4"],
        "spend": [10.0, 20.0, 30.0, 40.0],
    })


def refs():
    return pd.DataFrame({
        "client_id": ["A1", "B2", "E5"],
        "segment": ["x", "y", "z"],
    })


def test_exact_link_full_match():
    df_a = clients().head(2)
    df_b = refs().head(2)
    result = link_tables(df_a, df_b, "client_id", left_name="clients", right_name="refs")
    assert result.match_rate == 1.0
    assert result.matched_rows == 2
    assert result.unmatched_left == []
    assert result.unmatched_right == []
    assert result.joined["segment"].tolist() == ["x", "y"]
    assert "clients" in repr(result) and "refs" in repr(result)


def test_partial_link_reports_unmatched():
    result = link_tables(clients(), refs(), "client_id")
    assert result.match_rate == pytest.approx(2 / 4)
    assert result.match_rate_left == pytest.approx(2 / 4)
    assert result.match_rate_right == pytest.approx(2 / 3)
    assert result.matched_rows == 2
    assert result.unmatched_left == ["C3", "D4"]
    assert result.unmatched_right == ["E5"]


def test_directional_rates_differ_from_symmetric():
    left = pd.DataFrame({"id": ["A1", "B2"]})
    right = pd.DataFrame({"id": ["A1", "C3", "D4"]})
    result = link_tables(left, right, "id")
    assert result.match_rate_left == 0.5
    assert result.match_rate_right == pytest.approx(1 / 3)
    assert result.match_rate == pytest.approx(1 / 3)


def test_key_type_standardization_enables_match():
    left = pd.DataFrame({"postal_code": ["m5v 2t6", "K1A 0B1", "12345"]})
    right = pd.DataFrame({"fsa": ["M5V", "K1A"]})
    result = link_tables(
        left, right, "postal_code", right_on="fsa",
        left_key_type="fsa", right_key_type="fsa",
    )
    assert result.match_rate == 1.0
    assert result.joined["postal_code"].tolist() == ["M5V", "K1A"]


def test_key_type_normalizes_case_and_spaces():
    left = pd.DataFrame({"id": [" a1 ", "B2"]})
    right = pd.DataFrame({"id": ["A1", "b2 "]})
    result = link_tables(left, right, "id", left_key_type="client_id",
                         right_key_type="client_id")
    assert result.match_rate == 1.0


def test_left_join_keeps_unmatched():
    result = link_tables(clients(), refs(), "client_id", how="left")
    assert len(result.joined) == 4
    assert result.matched_rows == 2
    assert result.joined["segment"].isna().sum() == 2


def test_duplicates_reported_not_fatal():
    left = pd.DataFrame({"id": ["A1", "A1", "B2"]})
    right = pd.DataFrame({"id": ["A1"]})
    result = link_tables(left, right, "id")
    assert result.duplicates["left"] == 1
    assert result.matched_rows == 2


def test_nulls_reported():
    left = pd.DataFrame({"id": ["A1", None]})
    right = pd.DataFrame({"id": ["A1"]})
    result = link_tables(left, right, "id")
    assert result.nulls["left"] == 1


def test_dtype_mismatch_reported():
    left = pd.DataFrame({"id": [1, 2]})
    right = pd.DataFrame({"id": [1.0, 2.0]})
    result = link_tables(left, right, "id")
    assert result.dtype_mismatches and "int64" in result.dtype_mismatches[0]


def test_object_vs_numeric_key_raises_clearly():
    left = pd.DataFrame({"id": ["A1"]})
    right = pd.DataFrame({"id": [1]})
    with pytest.raises(ValueError, match="align dtypes"):
        link_tables(left, right, "id")


def test_missing_column_raises():
    with pytest.raises(KeyError, match="no column 'nope'"):
        link_tables(clients(), refs(), "nope")


def test_bad_how_raises():
    with pytest.raises(ValueError, match="how"):
        link_tables(clients(), refs(), "client_id", how="cross")


def test_tables_link_method(tmp_path):
    pd.DataFrame({"client_id": ["A1", "B2"], "v": [1, 2]}).to_csv(
        tmp_path / "clients.csv", index=False
    )
    pd.DataFrame({"client_id": ["A1"], "w": [9]}).to_csv(
        tmp_path / "refs.csv", index=False
    )
    result = Tables(tmp_path).link("clients", "refs", "client_id")
    assert result.left_table == "clients"
    assert result.match_rate == pytest.approx(0.5)
    assert result.joined["w"].tolist() == [9]
