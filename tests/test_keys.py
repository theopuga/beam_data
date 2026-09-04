"""Tests for identifier key standardization: shipped cleaners + registry."""

import pandas as pd
import pytest

from localdb import register_kind, standardize


def test_unknown_kind_raises():
    df = pd.DataFrame({"key": ["M5V 2T6"]})
    with pytest.raises(KeyError, match="Unknown key kind"):
        standardize(df, "key", kind="does_not_exist")


def test_register_kind_rejects_duplicate():
    register_kind("dup_kind", lambda s: s)
    with pytest.raises(ValueError, match="already registered"):
        register_kind("dup_kind", lambda s: s)
    register_kind("dup_kind", lambda s: s, overwrite=True)


def test_postal_code():
    df = pd.DataFrame({"key": ["m5v 2t6", "M5V-2T6", None, "12345-6789", "  K1A 0B1 "]})
    standardize(df, "key", kind="postal_code")
    assert df["key"].tolist() == ["M5V2T6", "M5V2T6", pd.NA, "12345", "K1A0B1"]


def test_fsa_extracts_first_three():
    df = pd.DataFrame({"key": ["m5v 2t6", "12345", None, "K1A 0B1"]})
    standardize(df, "key", kind="fsa")
    assert df["key"].tolist() == ["M5V", pd.NA, pd.NA, "K1A"]


def test_uk_postcode():
    df = pd.DataFrame({"key": [" ec1a 1bb ", "M1 1AE", "m60-1da", "CR2 6XH", "12345", None]})
    standardize(df, "key", kind="uk_postcode")
    assert df["key"].tolist() == ["EC1A 1BB", "M1 1AE", "M60 1DA", "CR2 6XH", pd.NA, pd.NA]


def test_cep():
    df = pd.DataFrame({"key": ["12227-000", "12227000", "12.227-000", "1234", None]})
    standardize(df, "key", kind="cep")
    assert df["key"].tolist() == ["12227-000", "12227-000", "12227-000", pd.NA, pd.NA]


def test_plz():
    df = pd.DataFrame({"key": ["70174", "DE-10115", "12 345", None]})
    standardize(df, "key", kind="plz")
    assert df["key"].tolist() == ["70174", "10115", "12345", pd.NA]


def test_client_id():
    df = pd.DataFrame({"key": [" ab 12 ", None, "X-9"]})
    standardize(df, "key", kind="client_id")
    assert df["key"].tolist() == ["AB12", pd.NA, "X-9"]


def test_phone():
    df = pd.DataFrame({"key": ["+1 (416) 555-1234", "416.555.1234", "1-800-555-1234", "1234", None]})
    standardize(df, "key", kind="phone")
    assert df["key"].tolist() == ["4165551234", "4165551234", "8005551234", "1234", pd.NA]


def test_email():
    df = pd.DataFrame({"key": ["Foo@Bar.COM ", " a@b.co", None]})
    standardize(df, "key", kind="email")
    assert df["key"].tolist() == ["foo@bar.com", "a@b.co", pd.NA]


def test_standardize_is_in_place_and_returns_df():
    df = pd.DataFrame({"key": ["m5v 2t6"]})
    out = standardize(df, "key", kind="postal_code")
    assert out is df
    assert df["key"].iloc[0] == "M5V2T6"
