"""Readers mapping file extensions to pandas loaders; extensible per project."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

Reader = Callable[..., pd.DataFrame]

_READERS: dict[str, Reader] = {}


def register_reader(ext: str, reader: Reader, overwrite: bool = False) -> None:
    """Register a loader for a file extension (e.g. "csv", "parquet").

    The reader receives the resolved Path plus any kwargs passed to read().
    """
    key = ext.lower().lstrip(".")
    if key in _READERS and not overwrite:
        raise ValueError(
            f"reader for {key!r} already registered; pass overwrite=True to replace"
        )
    _READERS[key] = reader


def supported_extensions() -> list[str]:
    """All extensions with a registered reader."""
    return sorted(_READERS)


def read(path: str | Path, **kwargs: Any) -> pd.DataFrame:
    """Read one data file into a DataFrame; format is chosen by extension.

    kwargs pass through to the underlying pandas loader (e.g. sep=, na_values=).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"{p} is not an existing file")
    ext = p.suffix.lower().lstrip(".")
    reader = _READERS.get(ext)
    if reader is None:
        raise ValueError(
            f"no reader registered for {ext!r}; supported: {supported_extensions()}"
        )
    return reader(p, **kwargs)


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, **kwargs)


def _read_tsv(path: Path, **kwargs: Any) -> pd.DataFrame:
    kwargs.setdefault("sep", "\t")
    return pd.read_csv(path, **kwargs)


def _read_parquet(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_parquet(path, **kwargs)


def _read_excel(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_excel(path, **kwargs)


def _read_json(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_json(path, **kwargs)


def _read_sqlite(path: Path, table: str | None = None, **kwargs: Any) -> pd.DataFrame:
    if table is None:
        raise ValueError("sqlite files need a table name: read(path, table=...)")
    with sqlite3.connect(path) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table}"', conn, **kwargs)


def _read_zip(path: Path, member: str | None = None, **kwargs: Any) -> pd.DataFrame:
    """Read a tabular file stored inside a .zip (csv/tsv members).

    Single-member zips read directly; multi-member zips need member=<name>.
    kwargs pass through to pd.read_csv.
    """
    import io
    import zipfile

    with zipfile.ZipFile(path) as z:
        members = [n for n in z.namelist() if not n.endswith("/")]
        if member is None:
            if len(members) != 1:
                preview = ", ".join(members[:5])
                raise ValueError(
                    f"{path} contains {len(members)} members; pass member= one of: {preview}"
                )
            member = members[0]
        elif member not in members:
            raise KeyError(f"member {member!r} not in {path}; members: {members}")
        data = z.read(member)
    inner_ext = member.rsplit(".", 1)[-1].lower()
    if inner_ext == "csv":
        return pd.read_csv(io.BytesIO(data), **kwargs)
    if inner_ext in ("tsv", "txt"):
        kwargs.setdefault("sep", "\t")
        return pd.read_csv(io.BytesIO(data), **kwargs)
    raise ValueError(f"zip member {member!r} is .{inner_ext}; only csv/tsv/txt supported")


register_reader("csv", _read_csv)
register_reader("tsv", _read_tsv)
register_reader("parquet", _read_parquet)
register_reader("pq", _read_parquet)
register_reader("xlsx", _read_excel)
register_reader("xls", _read_excel)
register_reader("json", _read_json)
register_reader("sqlite", _read_sqlite)
register_reader("db", _read_sqlite)
register_reader("zip", _read_zip)
