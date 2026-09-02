"""Package import works; run_audit is stubbed until Phase 7."""

import ds_audit_toolkit


def test_package_imports():
    assert ds_audit_toolkit.__version__ == "0.1.0"


def test_run_audit_exported():
    assert callable(ds_audit_toolkit.run_audit)
