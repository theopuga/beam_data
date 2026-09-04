"""Tests for Tables: folder of files, sqlite files, and duckdb queries."""

import sqlite3

import pandas as pd
import pytest

from localdb import Tables, read


@pytest.fixture()
def folder(tmp_path):
    pd.DataFrame({"id": [1, 2], "name": ["a", "b"]}).to_csv(tmp_path / "clients.csv", index=False)
    pd.DataFrame({"id": [1], "ref": ["x"]}).to_json(tmp_path / "refs.json", orient="records")
    return tmp_path


@pytest.fixture()
def sqlite_file(tmp_path):
    p = tmp_path / "data.sqlite"
    with sqlite3.connect(p) as conn:
        pd.DataFrame({"id": [1, 2], "amt": [10.0, 20.0]}).to_sql("trades", conn, index=False)
    return p


def test_folder_names(folder):
    assert Tables(folder).names() == ["clients", "refs"]


def test_folder_names_include_excel(tmp_path):
    pytest.importorskip("openpyxl")
    pd.DataFrame({"a": [1]}).to_excel(tmp_path / "sheet.xlsx", index=False)
    assert Tables(tmp_path).names() == ["sheet"]
    assert Tables(tmp_path).get("sheet")["a"].iloc[0] == 1


def test_folder_get_by_stem(folder):
    assert Tables(folder).get("clients")["name"].tolist() == ["a", "b"]


def test_folder_get_missing_raises(folder):
    with pytest.raises(KeyError, match="not found"):
        Tables(folder).get("nope")


def test_folder_ambiguous_stem_raises(folder):
    pd.DataFrame({"a": [1]}).to_parquet(folder / "clients.parquet")
    with pytest.raises(ValueError, match="ambiguous"):
        Tables(folder).get("clients")


def test_folder_get_passthrough_kwargs(folder):
    out = Tables(folder).get("clients", dtype={"id": "int64"})
    assert out["id"].tolist() == [1, 2]


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Tables(tmp_path / "nope")


def test_file_that_is_not_sqlite_raises(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        Tables(p)


def test_sqlite_names(sqlite_file):
    assert Tables(sqlite_file).names() == ["trades"]


def test_sqlite_get(sqlite_file):
    assert Tables(sqlite_file).get("trades")["amt"].tolist() == [10.0, 20.0]


def test_sqlite_query(sqlite_file):
    out = Tables(sqlite_file).query("SELECT id FROM trades WHERE id = 2")
    assert out["id"].tolist() == [2]


def test_folder_query_via_duckdb(folder):
    pytest.importorskip("duckdb")
    out = Tables(folder).query(
        "SELECT c.name FROM clients c JOIN refs r USING (id) ORDER BY c.name"
    )
    assert out["name"].tolist() == ["a"]


def test_folder_query_quoted_stems(tmp_path):
    pytest.importorskip("duckdb")
    pd.DataFrame({"id": [1, 2], "v": ["a", "b"]}).to_csv(tmp_path / "17-18 data.csv", index=False)
    out = Tables(tmp_path).query('SELECT id FROM "17-18 data" WHERE id = 2')
    assert out["id"].tolist() == [2]


def test_repr(folder):
    assert "tables=" in repr(Tables(folder))


def test_read_still_exported(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a\n7\n", encoding="utf-8")
    assert read(p)["a"].iloc[0] == 7
