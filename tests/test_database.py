"""Tests for Database: folder-as-db, sqlite files, and duckdb queries."""

import sqlite3

import pandas as pd
import pytest

from localdb import Database, read


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


def test_folder_lists_tables(folder):
    assert Database(folder).list_tables() == ["clients", "refs"]


def test_folder_get_table_by_stem(folder):
    assert Database(folder).get_table("clients")["name"].tolist() == ["a", "b"]


def test_folder_get_table_missing_raises(folder):
    with pytest.raises(KeyError, match="not found"):
        Database(folder).get_table("nope")


def test_folder_ambiguous_stem_raises(folder):
    pd.DataFrame({"a": [1]}).to_parquet(folder / "clients.parquet")
    with pytest.raises(ValueError, match="ambiguous"):
        Database(folder).get_table("clients")


def test_folder_get_table_passthrough_kwargs(folder):
    out = Database(folder).get_table("clients", dtype={"id": "int64"})
    assert out["id"].tolist() == [1, 2]


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Database(tmp_path / "nope")


def test_file_that_is_not_sqlite_raises(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        Database(p)


def test_sqlite_lists_tables(sqlite_file):
    assert Database(sqlite_file).list_tables() == ["trades"]


def test_sqlite_get_table(sqlite_file):
    assert Database(sqlite_file).get_table("trades")["amt"].tolist() == [10.0, 20.0]


def test_sqlite_query(sqlite_file):
    out = Database(sqlite_file).query("SELECT id FROM trades WHERE id = 2")
    assert out["id"].tolist() == [2]


def test_folder_query_via_duckdb(folder):
    pytest.importorskip("duckdb")
    out = Database(folder).query(
        "SELECT c.name FROM clients c JOIN refs r USING (id) ORDER BY c.name"
    )
    assert out["name"].tolist() == ["a"]


def test_folder_repr(folder):
    assert "tables=" in repr(Database(folder))


def test_read_still_exported(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a\n7\n", encoding="utf-8")
    assert read(p)["a"].iloc[0] == 7
