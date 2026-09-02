"""Pandera rule enforcement; auto-draft schemas to config/schemas/<dataset>.py.

pandera integration (audited against pandera 0.33):
    - Import namespace: `import pandera.pandas as pa` (canonical since the
      multi-backend split; not bare `import pandera`).
    - Auto-draft: `pandera.schema_inference.pandas.infer_schema(df)` infers
      dtype/nullability/uniqueness, then `pandera.io.pandas_io.to_script()`
      serializes it to an importable Python file — checked into
      config/schemas/<dataset>.py, hand-editable, version-controlled.
    - Enforcement: load the checked-in schema module, call
      `schema.validate(df, lazy=True)`; lazy mode collects ALL failure cases
      into one `pa.errors.SchemaErrors` (failure_cases dataframe) rather than
      raising on the first — mapped to SchemaValidationResult.failures.
    - Drafted schemas use strict=True (unexpected columns fail) and
      coerce=False (dtype drift is reported, not silently fixed) so the
      checked-in schema is a real contract.
"""

from typing import Any

from ds_audit_toolkit.types import SchemaValidationResult


def draft_schema(df: Any, dataset_name: str) -> SchemaValidationResult:
    """Infer dtype, nullability, uniqueness; write a pandera schema file.

    First run against a new dataset infers via pandera.schema_inference and
    writes config/schemas/<dataset>.py via pandera.io to_script().
    """
    raise NotImplementedError("auto-draft lands in Phase 4")


def validate(df: Any, dataset_name: str) -> SchemaValidationResult:
    """Enforce the checked-in (hand-editable, version-controlled) schema.

    Runs schema.validate(df, lazy=True) and collects SchemaErrors failure
    cases. Never regenerates the schema blindly; raises if no schema is
    checked in.
    """
    raise NotImplementedError("enforcement lands in Phase 4")
