"""Tests for the zip-query cache primitives in localdb.cache."""

import os

from localdb import cache


def _entry_dirs(root):
    d = root / "zip"
    return sorted(p.name for p in d.iterdir() if not p.name.startswith(".tmp-"))


def test_zip_cache_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALDB_CACHE_DIR", str(tmp_path / "custom"))
    root = cache.zip_cache_root()
    assert root == tmp_path / "custom"
    assert (root / "zip").is_dir()


def test_zip_key_changes_when_zip_changes(tmp_path):
    p = tmp_path / "z.zip"
    p.write_bytes(b"v1")
    key1 = cache.zip_key(p)
    os.utime(p, ns=(1_000_000_000, 1_000_000_000))
    p.write_bytes(b"v2-longer")
    assert cache.zip_key(p) != key1


def test_finalize_entry_reuses_existing_winner(tmp_path):
    root = tmp_path
    (root / "zip" / "key").mkdir(parents=True)
    (root / "zip" / "key" / "winner.txt").write_text("done")
    staging = cache.new_staging_dir(root, "key")
    (staging / "member_0.parquet").write_bytes(b"x")
    final = cache.finalize_entry(root, "key", staging)
    assert final == root / "zip" / "key"
    assert (final / "winner.txt").exists()
    assert not staging.exists()


def test_enforce_cap_default_cap_keeps_entries(tmp_path):
    entries = tmp_path / "zip"
    old = entries / "aaa"
    new = entries / "bbb"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "data.bin").write_bytes(b"0" * 100)
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    cache.enforce_cap(tmp_path)  # default 10 GB cap: nothing evicted
    assert _entry_dirs(tmp_path) == ["aaa", "bbb"]


def test_enforce_cap_tiny_cap_evicts_oldest(tmp_path, monkeypatch):
    entries = tmp_path / "zip"
    old = entries / "aaa"
    new = entries / "bbb"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "data.bin").write_bytes(b"0" * 100)
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    monkeypatch.setenv("LOCALDB_CACHE_MAX_GB", "0.0000001")  # ~100 bytes
    cache.enforce_cap(tmp_path)
    assert _entry_dirs(tmp_path) == ["bbb"]


def test_clean_stale_staging_removes_only_old(tmp_path):
    entries = tmp_path / "zip"
    stale = entries / ".tmp-key-old"
    fresh = entries / ".tmp-key-new"
    stale.mkdir(parents=True)
    fresh.mkdir(parents=True)
    os.utime(stale, ns=(1_000_000_000, 1_000_000_000))
    cache.clean_stale_staging(tmp_path)
    assert not stale.exists()
    assert fresh.exists()


def test_discard_entry(tmp_path):
    entry = tmp_path / "zip" / "key"
    entry.mkdir(parents=True)
    (entry / "member_0.parquet").write_bytes(b"x")
    cache.discard_entry(tmp_path, "key")
    assert not entry.exists()
