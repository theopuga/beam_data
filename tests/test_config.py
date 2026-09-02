"""Config contracts; parsing lands in Phase 1."""

import pytest

from ds_audit_toolkit.config import JoinConfig, PipelineConfig, SourceSpec, load_config


def test_defaults_match_plan():
    cfg = JoinConfig()
    assert cfg.match_threshold == 0.95
    assert cfg.fuzzy_fallback is True


def test_pipeline_config_skips_flags_without_target():
    cfg = PipelineConfig()
    assert cfg.target_column is None


def test_load_config_not_implemented():
    with pytest.raises(NotImplementedError):
        load_config("config/client_geo_join.yaml")


def test_source_spec_shape():
    spec = SourceSpec(conn="postgresql://x", table="t", key="k", key_type="fsa")
    assert (spec.conn, spec.table, spec.key, spec.key_type) == (
        "postgresql://x",
        "t",
        "k",
        "fsa",
    )
