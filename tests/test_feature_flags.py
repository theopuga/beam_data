"""Stubbed until Phases 5-6."""

import pytest

from ds_audit_toolkit.feature_flags import flag_features


def test_flag_features_not_implemented():
    with pytest.raises(NotImplementedError):
        flag_features(None, target_column="y")
