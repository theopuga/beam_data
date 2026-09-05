"""Best-effort on-disk cache for zip members used in SQL queries.

Entries live under <cache_root>/zip/<key>/, one directory per zip version,
holding one parquet file per tabular member (`member_<i>.parquet`, index =
position in the zip's namelist, so the member -> view-name mapping is
reproducible on a cache hit). The key is a hash of the zip's resolved path,
size and mtime_ns: replacing the zip yields a new key and the old entry is
evicted lazily by the size cap.

Everything here is advisory: callers catch failures and fall back to
per-query temp extraction.
"""

import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path

_ENTRY_SUBDIR = "zip"
_STAGING_PREFIX = ".tmp-"
_STAGING_MAX_AGE_S = 86400.0  # abandoned staging dirs older than a day
_DEFAULT_MAX_GB = 10.0


def zip_cache_root() -> Path:
    """Cache directory (created on demand): $LOCALDB_CACHE_DIR or platform default."""
    env = os.environ.get("LOCALDB_CACHE_DIR")
    if env:
        root = Path(env)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise RuntimeError("no cache directory available (set LOCALDB_CACHE_DIR)")
        root = Path(base) / "localdb" / "cache"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        root = Path(xdg if xdg else Path.home() / ".cache") / "localdb"
    (root / _ENTRY_SUBDIR).mkdir(parents=True, exist_ok=True)
    return root


def zip_key(zip_path: Path) -> str:
    """Stable-per-zip-version key: hash of resolved path, size and mtime_ns."""
    st = zip_path.stat()
    h = hashlib.sha1()
    h.update(str(zip_path.resolve()).encode("utf-8", "surrogateescape"))
    h.update(f"|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()


def max_bytes() -> int:
    """Cache size cap: $LOCALDB_CACHE_MAX_GB (float) or 10 GB."""
    raw = os.environ.get("LOCALDB_CACHE_MAX_GB")
    try:
        gb = float(raw) if raw else _DEFAULT_MAX_GB
    except ValueError:
        gb = _DEFAULT_MAX_GB
    return max(int(gb * 1024**3), 0)


def enforce_cap(root: Path) -> None:
    """Delete least-recently-used entries until the cache fits the cap."""
    entries = root / _ENTRY_SUBDIR
    if not entries.is_dir():
        return
    stats: list[tuple[float, Path, int]] = []
    total = 0
    for p in entries.iterdir():
        if p.name.startswith(_STAGING_PREFIX) or not p.is_dir():
            continue
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        total += size
        stats.append((p.stat().st_mtime, p, size))
    if total <= max_bytes():
        return
    for _, p, size in sorted(stats):  # oldest mtime first
        if total <= max_bytes():
            break
        shutil.rmtree(p, ignore_errors=True)
        total -= size


def discard_entry(root: Path, key: str) -> None:
    """Remove one entry (corrupt/incomplete cache healing)."""
    shutil.rmtree(root / _ENTRY_SUBDIR / key, ignore_errors=True)


def mark_failed(root: Path, key: str) -> None:
    """Remember that conversion failed for this key (skip retrying per query)."""
    (root / _ENTRY_SUBDIR / f"{key}.failed").touch()


def is_failed(root: Path, key: str) -> bool:
    return (root / _ENTRY_SUBDIR / f"{key}.failed").exists()


def clean_stale_staging(root: Path) -> None:
    """Best-effort removal of abandoned staging dirs older than a day."""
    entries = root / _ENTRY_SUBDIR
    if not entries.is_dir():
        return
    now = time.time()
    for p in entries.glob(_STAGING_PREFIX + "*"):
        try:
            if now - p.stat().st_mtime > _STAGING_MAX_AGE_S:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            continue


def new_staging_dir(root: Path, key: str) -> Path:
    """Fresh staging dir inside the cache; finalize() promotes it to the entry."""
    d = root / _ENTRY_SUBDIR / f"{_STAGING_PREFIX}{key}-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    return d


def finalize_entry(root: Path, key: str, staging: Path) -> Path:
    """Atomically publish the staged entry; if it already exists, reuse the winner."""
    final = root / _ENTRY_SUBDIR / key
    try:
        staging.rename(final)
        return final
    except OSError:
        if final.is_dir():  # another process finished the same entry first
            shutil.rmtree(staging, ignore_errors=True)
            return final
        raise
