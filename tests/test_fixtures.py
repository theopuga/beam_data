"""Fixture-backed tests for real-world mess patterns (runs on any clone).

Small checked-in equivalents of the gitignored real-data regressions: a
latin-1/semicolon/decimal-comma CSV with preamble rows and a barcode-id CSV
whose integer inference strips leading zeros.
"""

from pathlib import Path

import pandas as pd
import pytest

from localdb import Tables, register_kind, standardize

DATA = Path(__file__).parent / "data"


class TestMessyExtract:
    def get(self):
        return Tables(DATA).get(
            "messy_extract", sep=";", encoding="latin-1", skiprows=2,
            decimal=",", thousands=" ",
        )

    def test_kwargs_passthrough_reads_messy_file(self):
        df = self.get()
        assert df["nom"].iloc[0] == "Frédéric Côté"
        assert len(df) == 5
        assert df["montant"].iloc[0] == 1234.50

    def test_default_utf8_fails_loudly(self):
        with pytest.raises(UnicodeDecodeError):
            Tables(DATA).get("messy_extract", sep=";", skiprows=2)

    def test_client_id_house_format_survives(self):
        df = self.get()
        standardize(df, "id_client", "client_id")
        assert df["id_client"].tolist() == [f"C-0004{i}" for i in range(2, 7)]


class TestBarcodeIds:
    def test_leading_zeros_need_string_dtype(self):
        df = pd.read_csv(DATA / "barcode_ids.csv", dtype={"client_id": "string"})
        assert df["client_id"].iloc[0] == "0600001410008"
        naive = pd.read_csv(DATA / "barcode_ids.csv")
        assert naive["client_id"].iloc[0] == 600001410008

    def test_ean13_check_digit_kind_flags_corrupted_row(self):
        def ean13(col):
            def ok(s):
                if s is None or len(s) != 13 or not s.isdigit():
                    return False
                body, check = s[:12], int(s[12])
                total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
                return (10 - total % 10) % 10 == check

            return col.map(ok)

        register_kind("ean13_valid_fixture", ean13, overwrite=True)
        df = pd.read_csv(DATA / "barcode_ids.csv", dtype={"client_id": "string"})
        standardize(df, "client_id", "ean13_valid_fixture")
        assert df["client_id"].sum() == 2
