"""Tests for the connector, using sqlite so no real DB is needed."""

import pandas as pd
import pytest
import sqlalchemy

from ds_audit_toolkit.connectors import get_table


@pytest.fixture()
def sqlite_url(tmp_path):
    url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    df = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})
    engine = sqlalchemy.create_engine(url)
    try:
        df.to_sql("clients", engine, index=False)
    finally:
        engine.dispose()
    return url


def test_get_table_by_name(sqlite_url):
    out = get_table(sqlite_url, "clients")
    assert out.shape == (3, 2)
    assert out["name"].tolist() == ["a", "b", "c"]


def test_get_table_by_query(sqlite_url):
    out = get_table(sqlite_url, "SELECT id FROM clients WHERE id > 1")
    assert out["id"].tolist() == [2, 3]


def test_multiline_query_is_query(sqlite_url):
    out = get_table(sqlite_url, "select id\nfrom clients\nwhere id = 3")
    assert out["id"].tolist() == [3]


def test_missing_table_raises(sqlite_url):
    with pytest.raises(ValueError, match="not found"):
        get_table(sqlite_url, "nope")
