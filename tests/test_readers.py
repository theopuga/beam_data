"""Tests for file readers: builtins, extension dispatch, and registration."""

import pandas as pd
import pytest

from localdb import read, register_reader, supported_extensions


def test_read_csv(tmp_path):
    p = tmp_path / "t.csv"
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_csv(p, index=False)
    out = read(p)
    assert out["b"].tolist() == ["x", "y"]


def test_read_tsv_sep(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("a\tb\n1\tx\n2\ty\n", encoding="utf-8")
    assert read(p)["b"].tolist() == ["x", "y"]


def test_read_json(tmp_path):
    p = tmp_path / "t.json"
    pd.DataFrame({"a": [1, 2]}).to_json(p, orient="records")
    assert read(p)["a"].tolist() == [1, 2]


def test_read_parquet(tmp_path):
    pytest.importorskip("pyarrow")
    p = tmp_path / "t.parquet"
    pd.DataFrame({"a": [1, 2]}).to_parquet(p)
    assert read(p)["a"].tolist() == [1, 2]


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read(tmp_path / "nope.csv")


def test_unknown_extension_raises(tmp_path):
    p = tmp_path / "t.unknown"
    p.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="no reader registered"):
        read(p)


def test_supported_extensions_list_builtins():
    exts = supported_extensions()
    for e in ("csv", "tsv", "parquet", "json", "sqlite"):
        assert e in exts


def test_register_reader_custom():
    register_reader("customx", lambda p, **kw: pd.DataFrame({"v": [1]}))
    assert "customx" in supported_extensions()


def test_register_reader_duplicate_rejected():
    register_reader("dupx", lambda p, **kw: pd.DataFrame())
    with pytest.raises(ValueError, match="already registered"):
        register_reader("dupx", lambda p, **kw: pd.DataFrame())
    register_reader("dupx", lambda p, **kw: pd.DataFrame({"v": [9]}), overwrite=True)


def test_custom_reader_used_by_read(tmp_path):
    register_reader("weird", lambda p, **kw: pd.DataFrame({"v": [42]}), overwrite=True)
    p = tmp_path / "t.weird"
    p.write_text("anything", encoding="utf-8")
    assert read(p)["v"].iloc[0] == 42


def test_read_sqlite_rejects_bad_table_name(tmp_path):
    import sqlite3

    p = tmp_path / "t.sqlite"
    with sqlite3.connect(p) as conn:
        conn.execute("CREATE TABLE trades (id INTEGER)")
    with pytest.raises(ValueError, match="invalid sqlite table name"):
        read(p, table='trades"')
    with pytest.raises(ValueError, match="invalid sqlite table name"):
        read(p, table="trades;")


def test_read_zip_single_member(tmp_path):
    import zipfile

    p = tmp_path / "t.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("inner.csv", "a,b\n1,x\n2,y\n")
    assert read(p)["b"].tolist() == ["x", "y"]


def test_read_zip_tsv_member(tmp_path):
    import zipfile

    p = tmp_path / "t.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("CA.txt", "a\tb\n1\tx\n")
    assert read(p)["b"].iloc[0] == "x"


def test_read_zip_multi_member_needs_member_arg(tmp_path):
    import zipfile

    p = tmp_path / "t.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("one.csv", "a\n1\n")
        z.writestr("two.csv", "a\n2\n")
    with pytest.raises(ValueError, match="pass member="):
        read(p)
    assert read(p, member="two.csv")["a"].iloc[0] == 2


def test_read_zip_missing_member_raises(tmp_path):
    import zipfile

    p = tmp_path / "t.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("one.csv", "a\n1\n")
    with pytest.raises(KeyError, match="not in"):
        read(p, member="nope.csv")
