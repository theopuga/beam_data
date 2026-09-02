"""Pandera rule enforcement; auto-draft schemas to config/schemas/<dataset>.py."""

from typing import Any


def draft_schema(df: Any, dataset_name: str) -> Any:
    """Infer dtype, nullability, uniqueness; write a pandera schema file.

    First run against a new dataset writes config/schemas/<dataset>.py.
    """
    raise NotImplementedError("auto-draft lands in Phase 4")


def validate(df: Any, dataset_name: str) -> Any:
    """Enforce the checked-in (hand-editable, version-controlled) schema.

    Never regenerates the schema blindly; raises if no schema is checked in.
    """
    raise NotImplementedError("enforcement lands in Phase 4")
