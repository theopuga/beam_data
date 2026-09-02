"""Stubbed until Phases 2-3."""

import pandas as pd
import pytest

from ds_audit_toolkit.join_audit import audit_join


def test_audit_join_not_implemented():
    left = pd.DataFrame({"key": [1]})
    right = pd.DataFrame({"key": [1]})
    with pytest.raises(NotImplementedError):
        audit_join(left, right, key="key")
