"""Stubbed until Phase 1."""

import pandas as pd
import pytest

from ds_audit_toolkit.standardize import register_kind, standardize


def test_unknown_kind_raises():
    df = pd.DataFrame({"key": ["M5V 2T6"]})
    with pytest.raises(KeyError):
        standardize(df, "key", kind="does_not_exist")


def test_register_kind_extends_registry():
    calls = []

    def cleaner(col):
        calls.append(col)
        return col

    register_kind("test_kind", cleaner)
    from ds_audit_toolkit.standardize.registry import _REGISTRY

    assert "test_kind" in _REGISTRY
