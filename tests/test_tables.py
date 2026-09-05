"""Tests for Tables: folder of files, sqlite files, and duckdb queries."""

import sqlite3

import pandas as pd
import pytest

from localdb import Tables, read, register_reader


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


def test_custom_reader_extension_discovered(tmp_path):
    register_reader("feathery", lambda p, **kw: pd.DataFrame({"v": [7]}))
    (tmp_path / "extra.feathery").write_text("x", encoding="utf-8")
    ts = Tables(tmp_path)
    assert "extra" in ts.names()
    assert ts.get("extra")["v"].iloc[0] == 7


def test_sqlite_file_in_folder_is_not_a_table(tmp_path, sqlite_file):
    pd.DataFrame({"id": [1], "name": ["a"]}).to_csv(tmp_path / "clients.csv", index=False)
    ts = Tables(tmp_path)
    assert ts.names() == ["clients"]
    with pytest.raises(KeyError, match="not found"):
        ts.get("data")


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


def test_tables_link_per_side_kwargs(tmp_path):
    pytest.importorskip("pyarrow")
    pd.DataFrame({"client_id": ["007", "008"], "v": [1, 2]}).to_csv(
        tmp_path / "clients.csv", index=False
    )
    pd.DataFrame({"client_id": ["007", "008"], "w": [9, 8]}).to_parquet(
        tmp_path / "refs.parquet"
    )
    ts = Tables(tmp_path)
    with pytest.raises((ValueError, TypeError)):  # shared dtype= breaks the parquet side
        ts.link("clients", "refs", "client_id", dtype={"client_id": "string"})
    result = ts.link(
        "clients", "refs", "client_id", left_kwargs={"dtype": {"client_id": "string"}}
    )
    assert result.match_rate == 1.0
    assert result.joined["w"].tolist() == [9, 8]


def test_get_column_pruning_pushdown(tmp_path):
    pytest.importorskip("pyarrow")
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"], "c": [3.0, 4.0]}).to_parquet(
        tmp_path / "t.parquet")
    out = Tables(tmp_path).get("t", columns=["b", "a"])
    assert list(out.columns) == ["b", "a"]


def test_get_column_pruning_csv(tmp_path):
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_csv(tmp_path / "t.csv", index=False)
    out = Tables(tmp_path).get("t", columns=["b"])
    assert list(out.columns) == ["b"]


def test_get_column_pruning_sqlite(tmp_path, sqlite_file):
    out = Tables(sqlite_file).get("trades", columns=["amt"])
    assert list(out.columns) == ["amt"] and out["amt"].tolist() == [10.0, 20.0]


def test_get_column_pruning_json_reads_whole_and_filters(tmp_path):
    pd.DataFrame({"a": [1], "b": ["x"]}).to_json(tmp_path / "t.json", orient="records")
    out = Tables(tmp_path).get("t", columns=["a"])
    assert list(out.columns) == ["a"]


def test_get_columns_and_usecols_conflict(tmp_path):
    pd.DataFrame({"a": [1]}).to_csv(tmp_path / "t.csv", index=False)
    with pytest.raises(ValueError, match="not both"):
        Tables(tmp_path).get("t", columns=["a"], usecols=["a"])


def test_query_join_zip_member(tmp_path):
    pytest.importorskip("duckdb")
    pd.DataFrame({"id": [1], "name": ["a"]}).to_csv(tmp_path / "clients.csv", index=False)
    import zipfile

    with zipfile.ZipFile(tmp_path / "orders.zip", "w") as z:
        z.writestr("orders.csv", "id,amount\n1,9.5\n")
    out = Tables(tmp_path).query(
        "SELECT c.name, o.amount FROM clients c JOIN orders o USING (id)"
    )
    assert out["amount"].iloc[0] == 9.5


def test_query_zip_multi_member_views(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "archive.zip", "w") as z:
        z.writestr("one.csv", "id,v\n1,a\n")
        z.writestr("two.csv", "id,v\n2,b\n")
    ts = Tables(tmp_path)
    out = ts.query('SELECT * FROM "archive__two"')
    assert out["v"].iloc[0] == "b"


def test_query_survives_unreadable_table(tmp_path):
    pytest.importorskip("duckdb")
    pd.DataFrame({"id": [1], "v": ["a"]}).to_csv(tmp_path / "good.csv", index=False)
    (tmp_path / "bad.csv").write_bytes(b"caf\xe9;stuff\n1;2\n")  # not utf-8
    with pytest.warns(UserWarning, match="skipped"):
        out = Tables(tmp_path).query("SELECT * FROM good")
    assert out["v"].iloc[0] == "a"


def test_query_zip_without_tabular_members_warns(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "imgs.zip", "w") as z:
        z.writestr("pic.bin", "binary")
    with pytest.warns(UserWarning, match="no csv/tsv members"):
        out = Tables(tmp_path).query("SELECT 1 AS x")
    assert out["x"].iloc[0] == 1


def test_repr(folder):
    assert "tables=" in repr(Tables(folder))


def test_read_still_exported(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a\n7\n", encoding="utf-8")
    assert read(p)["a"].iloc[0] == 7


# --- zip query cache ---


def _cache_zip_dir():
    import os
    from pathlib import Path

    return Path(os.environ["LOCALDB_CACHE_DIR"]) / "zip"


def test_zip_query_caches_parquet_and_reuses(tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "orders.zip", "w") as z:
        z.writestr("orders.csv", "id,amount\n1,9.5\n")

    extract_calls = []
    real_extract = zipfile.ZipFile.extract

    def counting_extract(self, member, path=None, pwd=None):
        extract_calls.append(member)
        return real_extract(self, member, path, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "extract", counting_extract)
    ts = Tables(tmp_path)
    first = ts.query("SELECT sum(amount) AS total FROM orders")
    assert extract_calls == ["orders.csv"]
    entry = next(p for p in _cache_zip_dir().iterdir() if not p.name.startswith(".tmp-"))
    assert list(entry.glob("member_0.parquet"))

    second = ts.query("SELECT sum(amount) AS total FROM orders")
    assert extract_calls == ["orders.csv"]  # second query: no re-extraction
    assert second["total"].iloc[0] == first["total"].iloc[0] == 9.5


def test_zip_cache_invalidated_when_zip_rewritten(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    zip_path = tmp_path / "orders.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("orders.csv", "id,amount\n1,1.0\n")
    ts = Tables(tmp_path)
    assert ts.query("SELECT max(amount) AS m FROM orders")["m"].iloc[0] == 1.0

    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("orders.csv", "id,amount\n1,2.0\n")
    assert ts.query("SELECT max(amount) AS m FROM orders")["m"].iloc[0] == 2.0
    assert len(list(_cache_zip_dir().iterdir())) == 2  # both versions cached


def test_zip_cache_false_leaves_no_cache(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "orders.zip", "w") as z:
        z.writestr("orders.csv", "id,amount\n1,9.5\n")
    out = Tables(tmp_path, cache=False).query("SELECT sum(amount) AS t FROM orders")
    assert out["t"].iloc[0] == 9.5
    assert not _cache_zip_dir().exists() or list(_cache_zip_dir().iterdir()) == []


def test_zip_cache_corrupt_entry_self_heals(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "orders.zip", "w") as z:
        z.writestr("orders.csv", "id,amount\n1,9.5\n")
    ts = Tables(tmp_path)
    assert ts.query("SELECT sum(amount) AS t FROM orders")["t"].iloc[0] == 9.5

    entry = next(p for p in _cache_zip_dir().iterdir() if not p.name.startswith(".tmp-"))
    (entry / "member_0.parquet").write_bytes(b"not a parquet file")

    out = ts.query("SELECT sum(amount) AS t FROM orders")  # rebuilds and still answers
    assert out["t"].iloc[0] == 9.5
    assert len(list(_cache_zip_dir().iterdir())) == 1


def test_zip_cache_unwritable_dir_warns_and_falls_back(tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    import zipfile

    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a dir")  # cache root mkdir will fail on this
    monkeypatch.setenv("LOCALDB_CACHE_DIR", str(blocked))
    with zipfile.ZipFile(tmp_path / "orders.zip", "w") as z:
        z.writestr("orders.csv", "id,amount\n1,9.5\n")
    with pytest.warns(UserWarning, match="zip cache unavailable"):
        out = Tables(tmp_path).query("SELECT sum(amount) AS t FROM orders")
    assert out["t"].iloc[0] == 9.5


def test_zip_cache_multi_member_names_preserved(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "archive.zip", "w") as z:
        z.writestr("one.csv", "id,v\n1,a\n")
        z.writestr("two.csv", "id,v\n2,b\n")
    out = Tables(tmp_path).query('SELECT * FROM "archive__two"')
    assert out["v"].iloc[0] == "b"
    entry = next(p for p in _cache_zip_dir().iterdir() if not p.name.startswith(".tmp-"))
    assert sorted(p.name for p in entry.glob("*.parquet")) == ["member_0.parquet", "member_1.parquet"]


def test_zip_cache_nested_member_paths(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "bundle.zip", "w") as z:
        z.writestr("sub/dir/inner.csv", "id,v\n1,a\n")
    out = Tables(tmp_path).query('SELECT * FROM "bundle"')  # single member -> zip stem
    assert out["v"].iloc[0] == "a"


def test_zip_cache_unconvertible_member_marked_failed(tmp_path):
    pytest.importorskip("duckdb")
    import zipfile

    with zipfile.ZipFile(tmp_path / "legacy.zip", "w") as z:
        z.writestr("legacy.csv", "id,nom\n1,caf\xe9\n".encode("latin-1"))  # not utf-8
    ts = Tables(tmp_path)
    with pytest.warns(UserWarning, match="zip cache unavailable"):
        ts.query("SELECT 1 AS x")
    markers = [p for p in _cache_zip_dir().iterdir() if p.name.endswith(".failed")]
    assert len(markers) == 1  # conversion failed once, not silently retried
    with pytest.warns(UserWarning, match="previous conversion attempt failed"):
        ts.query("SELECT 1 AS x")  # later queries skip the build retry
