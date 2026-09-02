"""SQLAlchemy-backed connector with one signature regardless of DB engine."""

import re

import pandas as pd
import sqlalchemy

_QUERY_PATTERN = re.compile(r"^\s*(select|with|values|show|pragma)\b", re.IGNORECASE)


def get_table(conn_str: str, table_or_query: str) -> pd.DataFrame:
    """Pull a table or SQL query into a pandas DataFrame via SQLAlchemy.

    Args:
        conn_str: SQLAlchemy connection URL (declared in YAML config, not
            hardcoded). Secrets belong in `${VAR}` env references expanded by
            ds_audit_toolkit.config.load_config.
        table_or_query: Table name, or raw SQL — strings starting with
            SELECT/WITH/etc. or containing whitespace are treated as SQL.
    """
    engine = sqlalchemy.create_engine(conn_str)
    try:
        is_query = bool(_QUERY_PATTERN.match(table_or_query)) or " " in table_or_query.strip()
        if is_query:
            return pd.read_sql_query(sqlalchemy.text(table_or_query), engine)
        return pd.read_sql_table(table_or_query, engine)
    finally:
        engine.dispose()
