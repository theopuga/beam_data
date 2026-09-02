"""Stubbed until Phase 7."""

import pytest

from ds_audit_toolkit.reporting import render_report


def test_render_report_not_implemented():
    with pytest.raises(NotImplementedError):
        render_report({}, "out.html")
