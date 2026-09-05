"""Tests for numeric_advisory: flagging object columns that should be numeric."""

import pandas as pd

from localdb import numeric_advisory


def test_mixed_decimal_column_is_flagged():
    # the montant case: French-format and plain-float values in one column
    df = pd.DataFrame({"montant": ["1 234,56", "12,5", "1234.56", "N/A", "9"]})
    out = numeric_advisory(df)
    assert out["column"].tolist() == ["montant"]
    row = out.iloc[0]
    assert row["parseable_share"] == 1.0  # N/A excluded from the evidence
    assert row["decimal"] == ","  # dominant convention among decimal values
    assert row["unparsed_examples"] == []


def test_already_numeric_column_not_flagged():
    df = pd.DataFrame({
        "a": [1.5, 2.5],
        "b": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "c": [True, False],
    })
    assert numeric_advisory(df).empty


def test_text_column_not_flagged():
    df = pd.DataFrame({"name": ["alice", "bob", "carol"]})
    assert numeric_advisory(df).empty


def test_identifier_column_not_flagged():
    df = pd.DataFrame({"client_id": ["C-00042", "C-00043", "C-00044"]})
    assert numeric_advisory(df).empty


def test_grouped_numbers_parse():
    df = pd.DataFrame({"v": ["1.234.567,89", "1,234,567.89", "1 234 567"]})
    assert numeric_advisory(df)["column"].tolist() == ["v"]


def test_currency_and_percent_symbols_parse():
    df = pd.DataFrame({"v": ["$1,234.56", "12,50 €", "£9", "45%"]})
    assert numeric_advisory(df)["column"].tolist() == ["v"]


def test_unparsed_values_are_reported():
    df = pd.DataFrame({"v": ["1", "2", "oops", "3"]})
    out = numeric_advisory(df, threshold=0.7)
    assert out.iloc[0]["unparsed_examples"] == ["oops"]
    assert out.iloc[0]["parseable_share"] == 0.75


def test_below_threshold_not_flagged():
    df = pd.DataFrame({"v": ["1", "2", "3", "mostly text here"]})
    assert numeric_advisory(df).empty
    assert not numeric_advisory(df, threshold=0.7).empty


def test_missing_like_values_excluded_from_evidence():
    df = pd.DataFrame({"v": ["1", "-", "n/a", "", None, "2"]})
    out = numeric_advisory(df)
    assert out.iloc[0]["non_null"] == 2  # only "1" and "2" count


def test_plain_digit_strings_flagged_documenting_ambiguity():
    # bare digit strings (e.g. phone numbers read as text) look numeric —
    # the advisory surfaces that, it does not guess intent
    df = pd.DataFrame({"phone": ["4165551234", "4165551235"]})
    assert numeric_advisory(df)["column"].tolist() == ["phone"]
    # but punctuated phone numbers do not parse
    df = pd.DataFrame({"phone": ["416-555-1234", "416-555-1235"]})
    assert numeric_advisory(df).empty


def test_empty_frame_and_all_missing_column():
    assert numeric_advisory(pd.DataFrame()).empty
    df = pd.DataFrame({"v": [None, "N/A", "-"]})
    assert numeric_advisory(df).empty
