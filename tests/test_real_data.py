"""Real-data pilot tests: run against test_data/ when present, skip otherwise.

These lock in the ground truths observed in the first real-data audit (see
TODO.md). CI never sees test_data/ (gitignored), so every test here skips
there by design.
"""

from pathlib import Path

import pytest

from localdb import Tables

TEST_DATA = Path(__file__).parents[1] / "test_data"
LICENCE_CSV = TEST_DATA / "select_licence_and_registration_business_17-18.csv"
CHINOOK = TEST_DATA / "chinook.sqlite"

pytestmark = pytest.mark.skipif(not TEST_DATA.exists(), reason="test_data/ not present")


@pytest.mark.skipif(not LICENCE_CSV.exists(), reason="licence extracts not present")
class TestLicenceData:
    def test_discovery(self):
        names = Tables(TEST_DATA).names()
        assert any("business_17-18" in n for n in names)
        assert any("business_18-19" in n for n in names)

    def test_licence_link_full_left_coverage(self):
        result = Tables(TEST_DATA).link(
            "select_licence_and_registration_business_17-18",
            "select_licence_and_registration_business_18-19_final",
            left_on="Licence Number", right_on="Licence Number",
        )
        assert result.match_rate_left == 1.0

    def test_postal_to_fsa_link(self):
        import io
        import zipfile

        from localdb import link_tables

        z = zipfile.ZipFile(TEST_DATA / "CA.zip")
        geo = pd_read_geo(io.BytesIO(z.read("CA.txt")))
        b18 = Tables(TEST_DATA).get("select_licence_and_registration_business_18-19_final")
        result = link_tables(
            b18, geo, "Address Postal Code", right_on="fsa",
            left_key_type="fsa", right_key_type="fsa",
        )
        assert result.match_rate_left > 0.98


@pytest.mark.skipif(not CHINOOK.exists(), reason="chinook.sqlite not present")
class TestChinook:
    def test_discovery(self):
        assert len(Tables(CHINOOK).names()) == 11
        assert "Customer" in Tables(CHINOOK).names()
        assert "InvoiceLine" in Tables(CHINOOK).names()

    def test_sql_three_table_join(self):
        out = Tables(CHINOOK).query(
            """
            SELECT g.Name AS genre, SUM(il.UnitPrice * il.Quantity) AS revenue
            FROM InvoiceLine il
            JOIN Track t ON il.TrackId = t.TrackId
            JOIN Genre g ON t.GenreId = g.GenreId
            GROUP BY 1 ORDER BY revenue DESC LIMIT 1
            """
        )
        assert out["genre"].iloc[0] == "Rock"

    def test_invoice_customer_link(self):
        ts = Tables(CHINOOK)
        result = ts.link("Invoice", "Customer", left_on="CustomerId",
                         right_on="CustomerId")
        assert result.match_rate == 1.0
        assert result.matched_rows == len(ts.get("Invoice"))

    def test_email_phone_cleaners_on_real_rows(self):
        from localdb.keys import standardize

        cust = Tables(CHINOOK).get("Customer")
        standardize(cust, "Email", "email")
        assert (cust["Email"] == cust["Email"].str.lower()).all()
        standardize(cust, "Phone", "phone")
        nanp = cust["Phone"].dropna()[cust["Phone"].dropna().str.len() == 10]
        assert not nanp.str.startswith("1").any()


def pd_read_geo(buf):
    import pandas as pd

    return pd.read_csv(buf, sep="\t", header=None, usecols=[1], names=["fsa"])
