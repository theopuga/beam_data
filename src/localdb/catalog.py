"""Optional YAML catalog mapping dataset names to file paths, with ${VAR} expansion."""

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from localdb.tables import Tables

_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: str) -> str:
    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"environment variable {name!r} is not set")
        return os.environ[name]

    return _ENV_VAR.sub(repl, value)


def load_catalog(catalog_path: str | Path) -> dict[str, Path]:
    """Load a YAML catalog: dataset name -> file path.

    Lets projects declare their downloaded datasets once and reference them
    by name: tables = load_catalog("catalog.yaml"); df = read(tables["clients"]).
    """
    with open(catalog_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{catalog_path}: top-level YAML must be a mapping")
    catalog: dict[str, Path] = {}
    for name, path in raw.items():
        if not isinstance(path, str):
            raise ValueError(f"{catalog_path}: entry {name!r} must map to a path string")
        resolved = Path(_expand_env(path)).expanduser()
        if not resolved.is_absolute():
            resolved = Path(catalog_path).parent / resolved
        catalog[str(name)] = resolved
    return catalog


def tables_from_catalog(catalog_path: str | Path) -> "Tables":
    """Open the catalog's file tables as one Tables with short aliases.

    The flat catalog format doubles as the alias map: every entry becomes an
    alias for its file's stem inside the common parent folder, so get() and
    query() use the catalog's short names instead of unwieldy file stems.
    Entries that are SQLite files (or folders) are excluded — a .sqlite is
    its own Tables, not a folder table. Raises if the eligible entries span
    more than one parent folder.
    """
    from localdb.tables import Tables, _table_file

    catalog = load_catalog(catalog_path)
    groups: dict[Path, dict[str, str]] = {}
    for name, path in catalog.items():
        if path.is_file() and _table_file(path):
            groups.setdefault(path.parent, {})[name] = path.stem
    if not groups:
        raise ValueError(f"{catalog_path}: no file tables to open as a folder")
    if len(groups) > 1:
        parents = ", ".join(sorted(str(p) for p in groups))
        raise ValueError(
            f"{catalog_path}: catalog entries span multiple folders ({parents}); "
            "open each folder as its own Tables"
        )
    (parent, aliases), = groups.items()
    aliases = {name: stem for name, stem in aliases.items() if name != stem}
    return Tables(parent, aliases=aliases)
