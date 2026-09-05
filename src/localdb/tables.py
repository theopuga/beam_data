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

    def __init__(self, path: str | Path, cache: bool = True,
                 aliases: dict[str, str] | None = None,
                 clean_headers: bool = False) -> None:
        """cache=False skips the on-disk zip-query cache (per-query temp extraction).

        aliases= maps short names to file stems for get()/query() (real files
        take precedence when a stem collides with an alias); ignored for
        SQLite files, which name their own tables. clean_headers=True strips
        surrounding whitespace from column names on get() and in query()
        views (per-call override wins).
        """
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} does not exist")
        self._cache = cache
        self._aliases = dict(aliases or {})
        self._clean_headers = clean_headers
        self._is_sqlite = self.path.is_file() and self.path.suffix.lower() in _SQLITE_SUFFIXES
        if not self._is_sqlite and not self.path.is_dir():
            raise NotADirectoryError(
                f"{self.path} is neither a folder of tables nor a SQLite file"
            )

    def names(self) -> list[str]:
        """All table names available here: file stems plus aliases."""
        if self._is_sqlite:
            with sqlite3.connect(self.path) as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            return sorted(name for (name,) in rows)
        return sorted({p.stem for p in self.path.iterdir() if _table_file(p)}
                      | set(self._aliases))

    def get(self, name: str, columns: list[str] | None = None,
            **kwargs: Any) -> pd.DataFrame:
        """Read one table (file stem, or sqlite table name) into a DataFrame.

        columns= prunes the read to those columns where the format supports
        pushdown (parquet reads columns= directly; csv/tsv/excel/zip read
        with usecols=; sqlite selects the columns in SQL); other formats
        (e.g. json or custom readers) read whole and filter. Reads whole
        files either way — rows are not streamed. Aliases resolve to their
        file stem; a real file stem wins over an alias. columns= matches the
        file's raw header; with clean_headers the cleaned names come back.
        """
        kwargs.setdefault("clean_headers", self._clean_headers)
        if self._is_sqlite:
            return read(self.path, table=name, columns=columns, **kwargs)
        if name in self._aliases and name not in {
            p.stem for p in self.path.iterdir() if _table_file(p)
        }:
            name = self._aliases[name]  # real file stems win over aliases
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
            if kwargs.get("clean_headers"):  # no pushdown: filter by raw, cleaned comes back
                columns = [c.strip() if isinstance(c, str) else c for c in columns]
            return read(matches[0], **kwargs)[list(columns)]
        return read(matches[0], **kwargs)

    def query(self, sql: str, clean_headers: bool | None = None) -> pd.DataFrame:
        """Run SQL joining the tables (requires the `sql` extra: duckdb).

        Files become views named by their quoted stem (csv/tsv/parquet/json/
        xlsx supported; xlsx reads all columns as varchar). Zip members with
        csv/tsv content are converted to parquet in a local cache on first
        query ($LOCALDB_CACHE_DIR, size-capped; Tables(..., cache=False) for
        per-query temp extraction instead) — a single-tabular-member zip
        becomes the zip's stem view, a multi-member zip gets one view per
        member named "<stem>__<member>".
        SQLite files are queried directly via the stdlib sqlite3. Tables
        whose format duckdb cannot read are skipped with a warning. Aliases
        become views selecting from their stem's view (real stems win; an
        alias whose target view is missing is skipped with a warning).
        clean_headers=True (or the Tables default) registers views with
        surrounding whitespace stripped from their column names.
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
        clean = self._clean_headers if clean_headers is None else clean_headers
        try:
            skipped = []
            stems = sorted({p.stem for p in self.path.iterdir() if _table_file(p)})
            for stem in stems:
                for p in self._files_with_stem(stem):
                    ext = p.suffix.lower().lstrip(".")
                    if ext == "zip":
                        try:
                            extracted = self._register_zip_views(con, p, stem, clean)
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
                    source = f"{fn}('{p.as_posix()}'{options})"
                    try:
                        con.execute(f'CREATE VIEW "{stem}" AS {self._view_select(con, source, clean)}')
                    except (duckdb.Error, ValueError) as exc:
                        # e.g. non-utf8 csv, headers that collide when stripped:
                        # advisory, not fatal
                        skipped.append(f"{stem} ({exc})")
                    break
            for alias, target in sorted(self._aliases.items()):
                if alias in stems:
                    warnings.warn(
                        f"alias {alias!r} ignored: a file with that stem exists"
                    )
                    continue
                try:
                    con.execute(f'CREATE VIEW "{alias}" AS SELECT * FROM "{target}"')
                except duckdb.Error as exc:  # missing target / failed source view
                    skipped.append(f"alias {alias} -> {target} ({exc})")
            if skipped:
                warnings.warn(
                    f"tables not SQL-queryable and skipped: {', '.join(sorted(set(skipped)))}"
                )
            return con.execute(sql).df()
        finally:
            con.close()
            if extracted:
                shutil.rmtree(extracted, ignore_errors=True)

    def _register_zip_views(self, con: Any, zip_path: Path, stem: str,
                            clean: bool) -> str | None:
        """View the zip's tabular members in duckdb.

        With caching on, members are converted to parquet in the local cache
        on first query and later queries view the cached files (returns None
        — nothing to clean up). With caching off, members are extracted to a
        temp dir for this query; returns the temp dir for the caller to
        remove, or None if the zip holds no csv/tsv members (warned).
        Cache failures warn and fall back to per-query temp extraction.
        """
        import zipfile

        with zipfile.ZipFile(zip_path) as z:
            members = [
                m for m in z.namelist()
                if not m.endswith("/") and m.rsplit(".", 1)[-1].lower() in ("csv", "tsv", "txt")
            ]
        if not members:
            warnings.warn(f"zip {zip_path.name!r} has no csv/tsv members; skipped")
            return None
        if self._cache:
            try:
                from localdb import cache

                if cache.is_failed(cache.zip_cache_root(), cache.zip_key(zip_path)):
                    warnings.warn(
                        f"zip {zip_path.name!r}: previous conversion failed; skipped "
                        "(delete the <key>.failed marker in the cache dir, or pass "
                        "cache=False, to retry)"
                    )
                    return None
            except (OSError, RuntimeError):
                pass  # cache unavailable: fall through to the normal flow
            try:
                self._register_cached_zip_views(con, zip_path, stem, members, clean)
                return None
            except Exception as exc:  # noqa: BLE001 — advisory: cache is best-effort
                detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                warnings.warn(
                    f"zip cache unavailable for {zip_path.name!r} ({detail}); "
                    "using per-query temp extraction"
                )
        return self._register_temp_zip_views(con, zip_path, members, stem, clean)

    def _register_cached_zip_views(self, con: Any, zip_path: Path, stem: str,
                                   members: list[str], clean: bool) -> None:
        """View the zip's members from the parquet cache, building it if needed."""
        from localdb import cache

        root = cache.zip_cache_root()
        key = cache.zip_key(zip_path)
        if cache.is_failed(root, key):
            raise RuntimeError("previous conversion attempt failed for this zip")
        entry = root / "zip" / key
        if not entry.is_dir():
            try:
                self._build_zip_cache(root, key, zip_path, members)
                cache.enforce_cap(root)
            except Exception:  # don't retry the build on every query
                cache.mark_failed(root, key)
                raise
        names = self._zip_view_names(stem, members)
        try:
            self._create_parquet_views(con, entry, names, clean)
        except Exception:  # noqa: BLE001 — corrupt/incomplete entry: rebuild once
            cache.discard_entry(root, key)
            self._build_zip_cache(root, key, zip_path, members)
            self._create_parquet_views(con, entry, names, clean)

    def _build_zip_cache(self, root: Path, key: str, zip_path: Path,
                         members: list[str]) -> None:
        """Extract members, convert each to parquet via duckdb, publish atomically."""
        import zipfile

        import duckdb

        from localdb import cache

        cache.clean_stale_staging(root)
        staging = cache.new_staging_dir(root, key)
        try:
            with zipfile.ZipFile(zip_path) as z:
                for member in members:
                    z.extract(member, staging)
            builder = duckdb.connect()
            try:
                for i, member in enumerate(members):
                    src = (staging / member).resolve().as_posix().replace("'", "''")
                    dst = (staging / f"member_{i}.parquet").as_posix().replace("'", "''")
                    builder.execute(
                        f"COPY (SELECT * FROM read_csv_auto('{src}')) TO '{dst}'"
                    )
            finally:
                builder.close()
            for f in staging.rglob("*"):  # keep only the parquet in the entry
                if f.is_file() and f.suffix.lower() != ".parquet":
                    f.unlink()
            cache.finalize_entry(root, key, staging)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _zip_view_names(stem: str, members: list[str]) -> list[str]:
        """Deterministic member -> view-name mapping (zip stem, or stem__member)."""
        used: set[str] = set()
        names = []
        for i, member in enumerate(members):
            name = stem if len(members) == 1 else f"{stem}__{Path(member).stem}"
            if name in used:
                name = f"{name}_{i}"
            used.add(name)
            names.append(name)
        return names

    @staticmethod
    def _view_select(con: Any, source: str, clean: bool) -> str:
        """The SELECT clause for a view over a duckdb source expression.

        clean=True strips surrounding whitespace from the source's string
        column names (DESCRIBE gives the raw schema; padded columns are
        re-aliased). Headers that collide once stripped raise ValueError —
        callers treat that as advisory, like any unreadable source.
        """
        if not clean:
            return f"SELECT * FROM {source}"
        cols = [row[0] for row in
                con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
        stripped = [c.strip() for c in cols]
        dupes = sorted({c for c in stripped if stripped.count(c) > 1})
        if dupes:
            raise ValueError(f"cleaning headers collides columns into: {dupes}")
        select_list = ", ".join(
            f'"{c}" AS "{s}"' if c != s else f'"{c}"'
            for c, s in zip(cols, stripped)
        )
        return f"SELECT {select_list} FROM {source}"

    @staticmethod
    def _create_parquet_views(con: Any, entry: Path, names: list[str],
                              clean: bool) -> None:
        for i, name in enumerate(names):
            pq = (entry / f"member_{i}.parquet").as_posix().replace("'", "''")
            source = f"read_parquet('{pq}')"
            con.execute(
                f'CREATE OR REPLACE VIEW "{name}" AS {Tables._view_select(con, source, clean)}'
            )

    def _register_temp_zip_views(self, con: Any, zip_path: Path, members: list[str],
                                 stem: str, clean: bool) -> str | None:
        """Per-query path (cache off or unavailable): extract to temp, csv views."""
        import zipfile

        extracted = tempfile.mkdtemp(prefix="localdb_zip_")
        names = self._zip_view_names(stem, members)
        with zipfile.ZipFile(zip_path) as z:
            for i, member in enumerate(members):
                z.extract(member, extracted)
                path = (Path(extracted) / member).resolve()
                quoted = path.as_posix().replace("'", "''")
                source = f"read_csv_auto('{quoted}')"
                con.execute(f'CREATE VIEW "{names[i]}" AS {self._view_select(con, source, clean)}')
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
