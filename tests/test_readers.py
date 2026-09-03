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
