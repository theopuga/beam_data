"""Registry of known key types, each with its own cleaning function.

Shipped kinds (Phase 1): postal_code, fsa, client_id, phone, email.
New kinds register via `register_kind` without touching core logic.
"""

from collections.abc import Callable
from typing import Any

_REGISTRY: dict[str, Callable[[Any], Any]] = {}


def register_kind(kind: str, cleaner: Callable[[Any], Any]) -> None:
    """Register a cleaning function under a key `kind` name."""
    _REGISTRY[kind] = cleaner


def standardize(df: Any, column: str, kind: str) -> Any:
    """Apply the cleaning function registered for `kind` to df[column], in place."""
    if kind not in _REGISTRY:
        raise KeyError(f"Unknown key kind: {kind!r}. Registered: {sorted(_REGISTRY)}")
    raise NotImplementedError("key cleaners land in Phase 1")
