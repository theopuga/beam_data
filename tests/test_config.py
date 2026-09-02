"""Tests for config parsing and validation."""

from pathlib import Path

import pytest

from ds_audit_toolkit.config import JoinConfig, PipelineConfig, SourceSpec, load_config

EXAMPLE = str(Path(__file__).parents[1] / "config" / "client_geo_join.yaml")


def write_yaml(tmp_path, content):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(content, encoding="utf-8")
    return str(cfg)


def test_defaults_match_plan():
    cfg = JoinConfig()
    assert cfg.match_threshold == 0.95
    assert cfg.fuzzy_fallback is True


def test_pipeline_config_skips_flags_without_target():
    cfg = PipelineConfig()
    assert cfg.target_column is None


def test_source_spec_shape():
    spec = SourceSpec(conn="postgresql://x", table="t", key="k", key_type="fsa")
    assert (spec.conn, spec.table, spec.key, spec.key_type) == (
        "postgresql://x",
        "t",
        "k",
        "fsa",
    )


def test_load_example_config():
    cfg = load_config(EXAMPLE)
    assert set(cfg.sources) == {"clients", "geo"}
    assert cfg.sources["clients"].key_type == "postal_code"
    assert cfg.sources["geo"].key == "fsa"
    assert cfg.join.match_threshold == 0.95
    assert cfg.join.fuzzy_fallback is True
    assert cfg.target_column == "churned"
    assert cfg.time_column == "signup_date"


def test_missing_required_field_raises(tmp_path):
    path = write_yaml(tmp_path, "sources:\n  a:\n    conn: sqlite://x\n    table: t\n")
    with pytest.raises(ValueError, match="missing fields"):
        load_config(path)


def test_unknown_field_raises(tmp_path):
    path = write_yaml(
        tmp_path,
        "sources:\n  a:\n    conn: sqlite://x\n    table: t\n    key: k\n"
        "    key_type: fsa\n    typo_feild: x\n",
    )
    with pytest.raises(ValueError, match="unknown fields"):
        load_config(path)


def test_unknown_top_level_field_raises(tmp_path):
    path = write_yaml(
        tmp_path,
        "sources:\n  a:\n    conn: sqlite://x\n    table: t\n    key: k\n    key_type: fsa\n"
        "target_colum: y\n",
    )
    with pytest.raises(ValueError, match="unknown top-level"):
        load_config(path)


def test_no_sources_raises(tmp_path):
    path = write_yaml(tmp_path, "sources: {}\n")
    with pytest.raises(ValueError, match="at least one source"):
        load_config(path)


def test_bad_threshold_raises(tmp_path):
    path = write_yaml(
        tmp_path,
        "sources:\n  a:\n    conn: sqlite://x\n    table: t\n    key: k\n    key_type: fsa\n"
        "join:\n  match_threshold: 1.5\n",
    )
    with pytest.raises(ValueError, match="match_threshold"):
        load_config(path)


def test_join_defaults_fill_in(tmp_path):
    path = write_yaml(
        tmp_path,
        "sources:\n  a:\n    conn: sqlite://x\n    table: t\n    key: k\n    key_type: fsa\n",
    )
    cfg = load_config(path)
    assert cfg.join == JoinConfig()
    assert cfg.target_column is None


def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_URL", "postgresql://real/warehouse")
    path = write_yaml(
        tmp_path,
        "sources:\n  a:\n    conn: ${TEST_DB_URL}\n    table: t\n    key: k\n    key_type: fsa\n",
    )
    assert load_config(path).sources["a"].conn == "postgresql://real/warehouse"


def test_missing_env_var_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_DB_URL", raising=False)
    path = write_yaml(
        tmp_path,
        "sources:\n  a:\n    conn: ${TEST_DB_URL}\n    table: t\n    key: k\n    key_type: fsa\n",
    )
    with pytest.raises(ValueError, match="TEST_DB_URL.*not set"):
        load_config(path)
