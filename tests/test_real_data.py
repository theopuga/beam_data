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
QUEBEC = TEST_DATA / "messy_quebec_extract.csv"
COMPANIES_HOUSE = TEST_DATA / "BasicCompanyData-2026-09-01-part1_7.zip"
GITHUB = TEST_DATA / "github_comments"
FEBRL_A = TEST_DATA / "febrl4_A.csv"
FEBRL_B = TEST_DATA / "febrl4_B.csv"
BARCODES = TEST_DATA / "barcode_client_ids.csv"

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


@pytest.mark.skipif(not QUEBEC.exists(), reason="messy_quebec_extract.csv not present")
class TestMessyQuebec:
    def test_kwargs_passthrough_reads_messy_file(self):
        ts = Tables(TEST_DATA)
        df = ts.get(
            "messy_quebec_extract", sep=";", encoding="latin-1", skiprows=2,
            decimal=",", thousands=" ",
        )
        assert df["nom"].iloc[0] == "Frédéric Côté"
        assert len(df) == 5

    def test_default_utf8_fails_loudly(self):
        with pytest.raises(UnicodeDecodeError):
            Tables(TEST_DATA).get("messy_quebec_extract", sep=";", skiprows=2)

    def test_client_id_house_format_survives(self):
        from localdb.keys import standardize

        df = Tables(TEST_DATA).get(
            "messy_quebec_extract", sep=";", encoding="latin-1", skiprows=2
        )
        standardize(df, "client_id", "client_id")
        assert df["client_id"].tolist() == [f"C-0004{i}" for i in range(2, 7)]


@pytest.mark.skipif(not COMPANIES_HOUSE.exists(), reason="companies house zip not present")
class TestCompaniesHouse:
    def test_zip_targeted_read(self):
        ts = Tables(TEST_DATA)
        df = ts.get(
            "BasicCompanyData-2026-09-01-part1_7",
            usecols=[" CompanyNumber", "CompanyName", "RegAddress.PostCode"],
        )
        assert len(df) == 849_999
        assert df["RegAddress.PostCode"].notna().sum() > 800_000

    def test_postcodes_need_stripping_for_linking(self):
        from localdb.keys import standardize

        ts = Tables(TEST_DATA)
        df = ts.get(
            "BasicCompanyData-2026-09-01-part1_7",
            usecols=["RegAddress.PostCode"],
        ).dropna()
        standardize(df, "RegAddress.PostCode", "postal_code")
        assert df["RegAddress.PostCode"].str.contains(" ").sum() == 0


@pytest.mark.skipif(not GITHUB.exists() or not any(GITHUB.iterdir()),
                    reason="github parquet shards not present")
class TestGithubParquet:
    def test_shards_discovered_and_readable(self):
        ts = Tables(GITHUB)
        assert len(ts.names()) >= 7
        assert "2011-02-12" in ts.names()

    def test_cross_shard_sql_aggregation(self):
        ts = Tables(GITHUB)
        views = ts.names()
        union = " UNION ALL ".join(
            f"SELECT '{v}' AS day, actor_login FROM \"{v}\"" for v in views
        )
        out = ts.query(
            f"SELECT day, COUNT(*) AS comments FROM ({union}) "
            "GROUP BY day ORDER BY day"
        )
        assert out["comments"].sum() == 3738
        assert out["comments"].iloc[0] == 410


@pytest.mark.skipif(not (BARCODES.exists() and FEBRL_A.exists() and FEBRL_B.exists()),
                    reason="barcode/febrl files not present")
class TestIdentifiersAndFuzzyTrigger:
    def test_barcode_leading_zeros_need_string_dtype(self):
        import pandas as pd

        df = pd.read_csv(BARCODES, dtype={"client_id": "string"})
        assert df["client_id"].iloc[0] == "0600001410008"
        naive = pd.read_csv(BARCODES)
        assert naive["client_id"].iloc[0] == 600001410008

    def test_ean13_check_digit_kind(self):
        import pandas as pd

        from localdb import register_kind, standardize

        def ean13(col):
            def ok(s):
                if s is None or len(s) != 13 or not s.isdigit():
                    return False
                body, check = s[:12], int(s[12])
                total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
                return (10 - total % 10) % 10 == check

            return col.map(ok)

        register_kind("ean13_valid", ean13)
        df = pd.read_csv(BARCODES, dtype={"client_id": "string"})
        standardize(df, "client_id", "ean13_valid")
        assert df["client_id"].sum() == 10

    def test_febrl_ground_truth_and_exact_ceiling(self):
        import pandas as pd

        a = pd.read_csv(FEBRL_A)
        b = pd.read_csv(FEBRL_B)
        a["stem"] = a["rec_id"].str.extract(r"rec-(\d+)-org")
        b["stem"] = b["rec_id"].str.extract(r"rec-(\d+)-dup")
        true_pairs = len(set(a["stem"].dropna()) & set(b["stem"].dropna()))
        assert true_pairs == 5000

        ka = a[["postcode", "surname", "date_of_birth"]].fillna("").astype(str).agg(
            "|".join, axis=1)
        kb = b[["postcode", "surname", "date_of_birth"]].fillna("").astype(str).agg(
            "|".join, axis=1)
        coverage = len(set(ka) & set(kb)) / len(set(ka))
        assert coverage < 0.6
        assert 0 == len(set(a.drop(columns="rec_id").fillna("").astype(str).agg(
            "|".join, axis=1)) & set(b.drop(columns="rec_id").fillna("").astype(str).agg(
                "|".join, axis=1)))

    def test_fuzzy_beats_exact_ceiling_on_febrl(self):
        import pandas as pd

        from localdb import fuzzy_link_tables

        a = pd.read_csv(FEBRL_A)
        b = pd.read_csv(FEBRL_B)
        a["stem"] = a["rec_id"].str.extract(r"rec-(\d+)-org")
        b["stem"] = b["rec_id"].str.extract(r"rec-(\d+)-dup")

        result = fuzzy_link_tables(
            a, b,
            on=["postcode", "given_name", "surname", "date_of_birth"],
            block_on=["postcode", "surname"],
            weights={"postcode": 1.0, "given_name": 2.0, "surname": 2.0,
                     "date_of_birth": 1.0},
            threshold=0.75,
        )
        best = result.best_matches()
        best = best.merge(a["stem"].rename("left_stem"),
                          left_on="left_index", right_index=True)
        best["right_stem"] = best["right_index"].map(
            pd.Series(b["stem"].to_numpy(), index=b.index))
        correct = int((best["left_stem"] == best["right_stem"]).sum())
        recall = correct / 5000
        precision = correct / len(best)
        assert recall > 0.78, f"recall {recall:.3f} below acceptance bar"
        assert precision > 0.94, f"precision {precision:.3f} below acceptance bar"
