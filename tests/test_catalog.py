"""Tests for the optional YAML catalog."""

import pandas as pd
import pytest

from localdb import load_catalog, tables_from_catalog


def write(tmp_path, content, name="catalog.yaml"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_load_catalog(tmp_path):
    (tmp_path / "clients.csv").touch()
    p = write(tmp_path, "clients: clients.csv\nlookup: other/lookup.parquet\n")
    cat = load_catalog(p)
    assert cat["clients"] == tmp_path / "clients.csv"
    assert cat["lookup"] == tmp_path / "other" / "lookup.parquet"


def test_env_can_point_to_absolute_location(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere" / "big.parquet"
    monkeypatch.setenv("TEST_LOOKUP", str(target))
    p = write(tmp_path, "lookup: ${TEST_LOOKUP}\n")
    assert load_catalog(p)["lookup"] == target


def test_relative_paths_resolve_against_catalog_dir(tmp_path):
    p = write(tmp_path, "clients: data/clients.csv\n")
    cat = load_catalog(p)
    assert cat["clients"] == tmp_path / "data" / "clients.csv"


def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DATA_DIR", str(tmp_path / "dl"))
    p = write(tmp_path, "clients: ${TEST_DATA_DIR}/clients.csv\n")
    assert load_catalog(p)["clients"] == tmp_path / "dl" / "clients.csv"


def test_missing_env_var_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_DATA_DIR", raising=False)
    p = write(tmp_path, "clients: ${TEST_DATA_DIR}/clients.csv\n")
    with pytest.raises(ValueError, match="TEST_DATA_DIR.*not set"):
        load_catalog(p)


def test_non_mapping_value_raises(tmp_path):
    p = write(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="mapping"):
        load_catalog(p)


def test_non_string_path_raises(tmp_path):
    p = write(tmp_path, "clients: 123\n")
    with pytest.raises(ValueError, match="path string"):
        load_catalog(p)


# --- tables_from_catalog: the catalog as an alias map ---


def test_from_catalog_aliases_shared_folder(tmp_path):
    (tmp_path / "data").mkdir()
    pd.DataFrame({"id": [1], "v": ["a"]}).to_csv(tmp_path / "data" / "ugly-stem.csv", index=False)
    p = write(tmp_path, "companies: data/ugly-stem.csv\n")
    ts = tables_from_catalog(p)
    assert ts.get("companies")["v"].iloc[0] == "a"
    assert ts.get("ugly-stem")["v"].iloc[0] == "a"  # stem still works
    assert ts.names() == ["companies", "ugly-stem"]
    pytest.importorskip("duckdb")
    assert ts.query("SELECT v FROM companies")["v"].iloc[0] == "a"


def test_from_catalog_redundant_alias_dropped(tmp_path):
    pd.DataFrame({"id": [1]}).to_csv(tmp_path / "clients.csv", index=False)
    p = write(tmp_path, "clients: clients.csv\n")
    ts = tables_from_catalog(p)
    assert ts.names() == ["clients"]  # alias == stem: no duplicate name


def test_from_catalog_sqlite_entries_excluded(tmp_path):
    import sqlite3

    with sqlite3.connect(tmp_path / "warehouse.sqlite") as conn:
        pd.DataFrame({"id": [1]}).to_sql("t", conn, index=False)
    p = write(tmp_path, "warehouse: warehouse.sqlite\n")
    with pytest.raises(ValueError, match="no file tables"):
        tables_from_catalog(p)


def test_from_catalog_multi_folder_raises(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    pd.DataFrame({"id": [1]}).to_csv(tmp_path / "a" / "x.csv", index=False)
    pd.DataFrame({"id": [1]}).to_csv(tmp_path / "b" / "y.csv", index=False)
    p = write(tmp_path, "ax: a/x.csv\nby: b/y.csv\n")
    with pytest.raises(ValueError, match="multiple folders"):
        tables_from_catalog(p)


def test_from_catalog_env_expansion(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    pd.DataFrame({"id": [1], "v": ["a"]}).to_csv(downloads / "part1_7.zip.csv", index=False)
    monkeypatch.setenv("DL_DIR", str(downloads))
    p = write(tmp_path, "companies: ${DL_DIR}/part1_7.zip.csv\n")
    assert tables_from_catalog(p).get("companies")["v"].iloc[0] == "a"
