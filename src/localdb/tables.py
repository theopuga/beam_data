"""A set of already-downloaded tables: a folder of data files, or a SQLite file."""

import shutil
import sqlite3
import tempfile
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from localdb.link import LinkResult, link_tables
from localdb.readers.core import read, supported_extensions

_SQLITE_SUFFIXES = {".sqlite", ".db", ".sqlite3"}


def _table_suffixes() -> set[str]:
    """Registry-driven table extensions; sqlite files are tables of their own."""
    return {f".{ext}" for ext in supported_extensions()} - _SQLITE_SUFFIXES


def _table_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in _table_suffixes()


# get(columns=...) translates to the reader-native pruning kwarg per format;
# formats absent here (json, custom readers) read whole and filter.
_COLUMN_PASSTHROUGH = {
    "parquet": "columns", "pq": "columns",
    "csv": "usecols", "tsv": "usecols",
    "xlsx": "usecols", "xls": "usecols", "zip": "usecols",
}


class Tables:
    """Connect to a set of tables: a folder of data files, or a SQLite file.

    Table names are file stems; format is detected per file. Ambiguous stems
    (clients.csv and clients.parquet in one folder) raise, rather than guess.
    A .sqlite file inside a folder is not a table — open it as its own
    Tables (it is silently absent from the folder's names()).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} does not exist")
        self._is_sqlite = self.path.is_file() and self.path.suffix.lower() in _SQLITE_SUFFIXES
        if not self._is_sqlite and not self.path.is_dir():
            raise NotADirectoryError(
                f"{self.path} is neither a folder of tables nor a SQLite file"
            )

    def names(self) -> list[str]:
        """All table names available here."""
        if self._is_sqlite:
            with sqlite3.connect(self.path) as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            return sorted(name for (name,) in rows)
        return sorted({p.stem for p in self.path.iterdir() if _table_file(p)})

    def get(self, name: str, columns: list[str] | None = None,
            **kwargs: Any) -> pd.DataFrame:
        """Read one table (file stem, or sqlite table name) into a DataFrame.

        columns= prunes the read to those columns where the format supports
        pushdown (parquet reads columns= directly; csv/tsv/excel/zip read
        with usecols=; sqlite selects the columns in SQL); other formats
        (e.g. json or custom readers) read whole and filter. Reads whole
        files either way — rows are not streamed.
        """
        if self._is_sqlite:
            return read(self.path, table=name, columns=columns, **kwargs)
        if columns is not None and "usecols" in kwargs:
            raise ValueError("pass columns= or usecols=, not both")
        matches = sorted(
            p for p in self.path.iterdir()
            if p.is_file() and p.stem == name and _table_file(p)
        )
        if not matches:
            available = ", ".join(self.names()) or "(none)"
            raise KeyError(f"table {name!r} not found in {self.path}; available: {available}")
        if len(matches) > 1:
            names = ", ".join(p.name for p in matches)
            raise ValueError(f"ambiguous table {name!r}: {names}; remove one or rename")
        if columns is not None:
            ext = matches[0].suffix.lower().lstrip(".")
            kwarg = _COLUMN_PASSTHROUGH.get(ext)
            if kwarg:
                kwargs[kwarg] = columns
                return read(matches[0], **kwargs)
            return read(matches[0], **kwargs)[list(columns)]
        return read(matches[0], **kwargs)

    def query(self, sql: str) -> pd.DataFrame:
        """Run SQL joining the tables (requires the `sql` extra: duckdb).

        Files become views named by their quoted stem (csv/tsv/parquet/json/
        xlsx supported; xlsx reads all columns as varchar). Zip members with
        csv/tsv content are extracted to a temp dir for the query — a
        single-tabular-member zip becomes the zip's stem view, a multi-
        member zip gets one view per member named "<stem>__<member>".
        SQLite files are queried directly via the stdlib sqlite3. Tables
        whose format duckdb cannot read are skipped with a warning.
        """
        if self._is_sqlite:
            with sqlite3.connect(self.path) as conn:
                return pd.read_sql_query(sql, conn)
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError(
                "SQL across tables requires the `sql` extra: pip install localdb[sql]"
            ) from exc
        con = duckdb.connect()
        extracted: str | None = None
        try:
            skipped = []
            for stem in self.names():
                for p in self._files_with_stem(stem):
                    ext = p.suffix.lower().lstrip(".")
                    if ext == "zip":
                        try:
                            extracted = self._register_zip_views(con, p, stem)
                        except Exception as exc:  # noqa: BLE001 — advisory: skip broken zips
                            skipped.append(f"{stem} ({exc})")
                        break
                    fn = {
                        "csv": "read_csv_auto",
                        "tsv": "read_csv_auto",
                        "parquet": "read_parquet",
                        "pq": "read_parquet",
                        "json": "read_json_auto",
                        "xlsx": "read_xlsx",
                        "xls": "read_xlsx",
                    }.get(ext)
                    if fn is None:
                        skipped.append(stem)
                        break
                    options = ", header = true, all_varchar = true" if fn == "read_xlsx" else ""
                    try:
                        con.execute(
                            f'CREATE VIEW "{stem}" AS '
                            f"SELECT * FROM {fn}('{p.as_posix()}'{options})"
                        )
                    except duckdb.Error as exc:  # e.g. non-utf8 csv: advisory, not fatal
                        skipped.append(f"{stem} ({exc})")
                    break
            if skipped:
                warnings.warn(
                    f"tables not SQL-queryable and skipped: {', '.join(sorted(set(skipped)))}"
                )
            return con.execute(sql).df()
        finally:
            con.close()
            if extracted:
                shutil.rmtree(extracted, ignore_errors=True)

    def _register_zip_views(self, con: Any, zip_path: Path, stem: str) -> str | None:
        """Extract the zip's tabular members to a temp dir; view them in duckdb.

        One tabular member -> view named by the zip stem; several members ->
        one view each, named "<stem>__<member-stem>" (dup member stems get a
        numeric suffix). Non-tabular members are ignored. Returns the temp
        dir for the caller to remove after the query; None if the zip holds
        no csv/tsv members (warned).
        """
        import zipfile

        members = [
            m for m in zipfile.ZipFile(zip_path).namelist()
            if not m.endswith("/") and m.rsplit(".", 1)[-1].lower() in ("csv", "tsv", "txt")
        ]
        if not members:
            warnings.warn(f"zip {zip_path.name!r} has no csv/tsv members; skipped")
            return None
        extracted = tempfile.mkdtemp(prefix="localdb_zip_")
        used: set[str] = set()
        with zipfile.ZipFile(zip_path) as z:
            for i, member in enumerate(members):
                z.extract(member, extracted)
                path = (Path(extracted) / member).resolve()
                name = stem if len(members) == 1 else f"{stem}__{Path(member).stem}"
                if name in used:
                    name = f"{name}_{i}"
                used.add(name)
                con.execute(
                    f'CREATE VIEW "{name}" AS '
                    f"SELECT * FROM read_csv_auto('{path.as_posix()}')"
                )
        return extracted

    def link(self, left_table: str, right_table: str, left_on: str,
             right_on: str | None = None, left_key_type: str | None = None,
             right_key_type: str | None = None, how: str = "inner",
             left_kwargs: dict[str, Any] | None = None,
             right_kwargs: dict[str, Any] | None = None,
             **get_kwargs: Any) -> LinkResult:
        """Link two tables in this set on identifier columns.

        Convenience over get() + link_tables: both tables are read, keys are
        standardized per the given key types, and a LinkResult (joined table
        + match report) is returned. See localdb.link.link_tables.

        Read kwargs shared by both sides go through get_kwargs; per-side read
        kwargs (e.g. only one side needs dtype= or encoding=) go through
        left_kwargs/right_kwargs, which win on conflicts.
        """
        left = self.get(left_table, **{**get_kwargs, **(left_kwargs or {})})
        right = self.get(right_table, **{**get_kwargs, **(right_kwargs or {})})
        return link_tables(
            left,
            right,
            left_on,
            right_on=right_on,
            left_key_type=left_key_type,
            right_key_type=right_key_type,
            how=how,
            left_name=left_table,
            right_name=right_table,
        )

    def _files_with_stem(self, stem: str) -> list[Path]:
        return sorted(p for p in self.path.iterdir() if p.stem == stem and _table_file(p))

    def __repr__(self) -> str:
        kind = "sqlite" if self._is_sqlite else "folder"
        return f"Tables({kind}: {self.path}, tables={self.names()})"
