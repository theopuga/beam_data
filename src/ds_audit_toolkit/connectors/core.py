"""SQLAlchemy-backed connector with one signature regardless of DB engine."""

from typing import Any


def get_table(conn_str: str, table_or_query: str) -> Any:
    """Pull a table or SQL query into a pandas DataFrame via SQLAlchemy.

    Args:
        conn_str: SQLAlchemy connection URL (declared in YAML config, not hardcoded).
        table_or_query: Table name or raw SQL query.
    """
    raise NotImplementedError("connectors land in Phase 1")


def load_sources_config(config_path: str) -> dict:
    """Load and validate the `sources:` section of a pipeline YAML config."""
    raise NotImplementedError("connectors land in Phase 1")
