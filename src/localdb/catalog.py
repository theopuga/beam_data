"""Optional YAML catalog mapping dataset names to file paths, with ${VAR} expansion."""

import os
import re
from pathlib import Path

import yaml

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
