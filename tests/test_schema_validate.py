"""Stubbed until Phase 4."""

import pytest

from ds_audit_toolkit.schema_validate import validate


def test_validate_not_implemented():
    with pytest.raises(NotImplementedError):
        validate(None, "some_dataset")
