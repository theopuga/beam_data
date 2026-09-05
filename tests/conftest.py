"""Shared fixtures: keep the zip-query cache out of the user's real cache dir."""

import pytest


@pytest.fixture(autouse=True)
def _local_zip_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALDB_CACHE_DIR", str(tmp_path / "zipcache"))
