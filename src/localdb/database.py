"""A downloaded data folder (or SQLite file) treated as the database itself."""

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from localdb.readers.core import read, supported_extensions

_SQLITE_SUFFIXES = {".sqlite", ".db", ".sqlite3"}
_SQL_EXTENSIONS = {".csv", ".tsv", ".parquet", ".pq", ".json"}


class Database:
    """A folder of data files, or a single SQLite file, queried by table name.

    Table names are file stems; format is detected per file. Ambiguous stems
    (clients.csv and clients.parquet in one folder) raise, rather than guess.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} does not exist")
        self._is_sqlite = self.path.is_file() and self.path.suffix.lower() in _SQLITE_SUFFIXES
        if not self._is_sqlite and not self.path.is_dir():
            raise NotADirectoryError(
                f"{self.path} is neither a data folder nor a SQLite file"
            )

    def list_tables(self) -> list[str]:
        """All table names discoverable in this database."""
        if self._is_sqlite:
            with sqlite3.connect(self.path) as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            return sorted(name for (name,) in rows)
        return sorted({p.stem for p in self.path.iterdir() if p.suffix.lower() in _SQL_EXTENSIONS})

    def get_table(self, name: str, **kwargs: Any) -> pd.DataFrame:
        """Read one table (file stem, or sqlite table name) into a DataFrame."""
        if self._is_sqlite:
            return read(self.path, table=name, **kwargs)
        matches = sorted(
            p for p in self.path.iterdir()
            if p.is_file()
            and p.stem == name
            and p.suffix.lower().lstrip(".") in supported_extensions()
        )
        if not matches:
            available = ", ".join(self.list_tables()) or "(none)"
            raise KeyError(f"table {name!r} not found in {self.path}; available: {available}")
        if len(matches) > 1:
            names = ", ".join(p.name for p in matches)
            raise ValueError(f"ambiguous table {name!r}: {names}; remove one or rename")
        return read(matches[0], **kwargs)

    def query(self, sql: str) -> pd.DataFrame:
        """Run SQL over the folder's tables (requires the `sql` extra: duckdb).

        Files become views named by their stem (csv/parquet/json supported).
        SQLite databases are queried directly via the stdlib sqlite3.
        """
        if self._is_sqlite:
            with sqlite3.connect(self.path) as conn:
                return pd.read_sql_query(sql, conn)
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError(
                "SQL over file folders requires the `sql` extra: pip install localdb[sql]"
            ) from exc
        con = duckdb.connect()
        try:
            for stem in self.list_tables():
                for p in self._files_with_stem(stem):
                    ext = p.suffix.lower().lstrip(".")
                    fn = {"csv": "read_csv_auto", "tsv": "read_csv_auto", "parquet": "read_parquet", "pq": "read_parquet", "json": "read_json_auto"}.get(ext)
                    if fn is None:
                        continue
                    con.execute(
                        f"CREATE VIEW {stem} AS SELECT * FROM {fn}('{p.as_posix()}')"
                    )
                    break
            return con.execute(sql).df()
        finally:
            con.close()

    def _files_with_stem(self, stem: str) -> list[Path]:
        return sorted(
            p for p in self.path.iterdir()
            if p.is_file() and p.stem == stem and p.suffix.lower() in _SQL_EXTENSIONS
        )

    def __repr__(self) -> str:
        kind = "sqlite" if self._is_sqlite else "folder"
        return f"Database({kind}: {self.path}, tables={self.list_tables()})"
