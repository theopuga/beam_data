"""Stubbed until Phase 1."""

import pytest

from ds_audit_toolkit.connectors import get_table


def test_get_table_not_implemented():
    with pytest.raises(NotImplementedError):
        get_table("postgresql://localhost/test", "some_table")
