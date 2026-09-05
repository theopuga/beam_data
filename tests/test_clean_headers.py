"""Tests for clean_headers: padded column names stripped on read/get/query."""

import sqlite3
import zipfile

import pandas as pd
import pytest

from localdb import Tables, read, register_reader
from localdb.readers.core import strip_column_names


@pytest.fixture()
def padded_folder(tmp_path):
    # pandas preserves padded csv headers (unlike duckdb's csv reader)
    (tmp_path / "companies.csv").write_text(
        " CompanyNumber, Status\n1,active\n2,closed\n", encoding="utf-8"
    )
    pd.DataFrame({" a": [1], " b": [2]}).to_json(
        tmp_path / "refs.json", orient="records"
    )
    return tmp_path


def test_strip_column_names_strips_in_place():
    df = pd.DataFrame(columns=[" a", "b ", "  c  ", 7])
    out = strip_column_names(df)
    assert list(out.columns) == ["a", "b", "c", 7]  # non-string names untouched


def test_strip_column_names_collision_raises():
    df = pd.DataFrame({"x": [1], " x": [2]})
    with pytest.raises(ValueError, match="collides"):
        strip_column_names(df)


def test_strip_column_names_whitespace_only_raises():
    df = pd.DataFrame(columns=["   "])
    with pytest.raises(ValueError, match="whitespace"):
        strip_column_names(df)


def test_read_clean_headers_opt_in(padded_folder):
    raw = read(padded_folder / "companies.csv")
    assert list(raw.columns) == [" CompanyNumber", " Status"]
    clean = read(padded_folder / "companies.csv", clean_headers=True)
    assert list(clean.columns) == ["CompanyNumber", "Status"]


def test_read_clean_headers_never_forwarded(tmp_path):
    seen = {}

    def reader(path, **kwargs):  # custom readers must not see the flag
        seen.update(kwargs)
        return pd.DataFrame({" a": [1]})

    register_reader("spy", reader, overwrite=True)
    (tmp_path / "t.spy").write_text("x", encoding="utf-8")
    out = read(tmp_path / "t.spy", clean_headers=True)
    assert "clean_headers" not in seen
    assert list(out.columns) == ["a"]


def test_get_default_leaves_headers_padded(padded_folder):
    assert list(Tables(padded_folder).get("companies").columns) == [
        " CompanyNumber", " Status"
    ]


def test_get_instance_default_cleans(padded_folder):
    out = Tables(padded_folder, clean_headers=True).get("companies")
    assert list(out.columns) == ["CompanyNumber", "Status"]


def test_get_per_call_overrides_instance_default(padded_folder):
    assert list(
        Tables(padded_folder).get("companies", clean_headers=True).columns
    ) == ["CompanyNumber", "Status"]
    assert list(
        Tables(padded_folder, clean_headers=True).get("companies", clean_headers=False).columns
    ) == [" CompanyNumber", " Status"]


def test_get_columns_pushdown_matches_raw_header_returns_cleaned(padded_folder):
    # csv pushdown (usecols=) matches the file's raw header...
    out = Tables(padded_folder, clean_headers=True).get("companies", columns=[" CompanyNumber"])
    assert list(out.columns) == ["CompanyNumber"]
    assert out["CompanyNumber"].tolist() == [1, 2]


def test_get_columns_no_pushdown_filters_cleaned_names(padded_folder):
    # json has no pushdown: read whole, filter — cleaned names expected
    ts = Tables(padded_folder, clean_headers=True)
    assert list(ts.get("refs", columns=["a"]).columns) == ["a"]
    raw = Tables(padded_folder).get("refs", columns=[" a"])
    assert list(raw.columns) == [" a"]


def test_get_sqlite_clean_headers(tmp_path):
    p = tmp_path / "data.sqlite"
    with sqlite3.connect(p) as conn:
        conn.execute('CREATE TABLE trades (" amount" REAL, side TEXT)')
        conn.execute("INSERT INTO trades VALUES (1.5, 'buy')")
    out = Tables(p, clean_headers=True).get("trades")
    assert list(out.columns) == ["amount", "side"]


def test_query_default_leaves_headers_raw(tmp_path):
    pytest.importorskip("duckdb")
    # parquet preserves padded names; duckdb's csv reader strips its own
    pd.DataFrame({" a": [1, 2], "b": [3, 4]}).to_parquet(tmp_path / "t.parquet")
    ts = Tables(tmp_path)
    assert ts.query('SELECT " a" AS v FROM t')["v"].tolist() == [1, 2]


def test_query_clean_headers_per_call(tmp_path):
    pytest.importorskip("duckdb")
    pd.DataFrame({" a": [1, 2], "b": [3, 4]}).to_parquet(tmp_path / "t.parquet")
    ts = Tables(tmp_path)
    assert ts.query("SELECT a + b AS s FROM t", clean_headers=True)["s"].tolist() == [4, 6]


def test_query_instance_default_clean(tmp_path):
    pytest.importorskip("duckdb")
    pd.DataFrame({" a": [1, 2], "b": [3, 4]}).to_parquet(tmp_path / "t.parquet")
    assert Tables(tmp_path, clean_headers=True).query("SELECT a FROM t")["a"].tolist() == [1, 2]


def test_query_clean_collision_skips_table_advisory(tmp_path):
    pytest.importorskip("duckdb")
    pd.DataFrame({"x": [1], " x": [2]}).to_parquet(tmp_path / "bad.parquet")
    pd.DataFrame({"ok": [7]}).to_parquet(tmp_path / "good.parquet")
    ts = Tables(tmp_path)
    with pytest.warns(UserWarning, match="skipped.*bad"):
        out = ts.query("SELECT ok FROM good", clean_headers=True)
    assert out["ok"].iloc[0] == 7


def test_query_zip_cached_with_clean_headers(tmp_path):
    pytest.importorskip("duckdb")
    from localdb import cache

    folder = tmp_path / "zips"
    folder.mkdir()
    with zipfile.ZipFile(folder / "members.zip", "w") as z:
        z.writestr("m.csv", "a, b\n1, 2\n")
    ts = Tables(folder)
    assert ts.query("SELECT a FROM members", clean_headers=True)["a"].tolist() == [1]
    assert (cache.zip_cache_root() / "zip").is_dir()  # served from the cache
    # same cache entry serves the uncleaned view too (clean is view-time only)
    assert ts.query('SELECT "a" FROM members')["a"].tolist() == [1]


def test_query_zip_temp_path_with_clean_headers(tmp_path):
    pytest.importorskip("duckdb")
    folder = tmp_path / "zips"
    folder.mkdir()
    with zipfile.ZipFile(folder / "members.zip", "w") as z:
        z.writestr("m.csv", "a, b\n1, 2\n")
    out = Tables(folder, cache=False).query("SELECT a FROM members", clean_headers=True)
    assert out["a"].tolist() == [1]
