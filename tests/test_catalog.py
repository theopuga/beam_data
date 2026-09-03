"""Tests for the optional YAML catalog."""

import pytest

from localdb import load_catalog


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
