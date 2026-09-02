"""Pandera rule enforcement; auto-draft schemas to config/schemas/<dataset>.py.

pandera integration (audited against pandera 0.33):
    - Import namespace: `import pandera.pandas as pa` (canonical since the
      multi-backend split; not bare `import pandera`).
    - Auto-draft: `pandera.schema_inference.pandas.infer_schema(df)` infers
      dtype/nullability plus min/max range checks, then
      `pandera.io.pandas_io.to_script()` serializes it to an importable
      Python file — checked into config/schemas/<dataset>.py,
      hand-editable, version-controlled. Drafted schemas are pinned to
      strict=True (unexpected columns fail) and coerce=False (dtype drift is
      reported, not silently fixed) so the checked-in file is a real
      contract. Serialization requires `black` (pandera hard-codes it inside
      to_script; it is not an optional dependency there).
    - Enforcement: load the checked-in schema module, call
      `schema.validate(df, lazy=True)`; lazy mode collects ALL failure cases
      into one `pa.errors.SchemaErrors` (failure_cases dataframe) rather
      than raising on the first — mapped to SchemaValidationResult.failures.
    - validate() never regenerates the schema blindly: a missing checked-in
      schema raises FileNotFoundError pointing at draft_schema.
"""

import importlib.util
import re
import warnings
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa
from pandera.io.pandas_io import to_script
from pandera.schema_inference.pandas import infer_schema

from ds_audit_toolkit.types import SchemaValidationResult

_DATASET_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _schema_path(dataset_name: str, schema_dir: str) -> Path:
    """Resolve <schema_dir>/<dataset>.py, rejecting unsafe dataset names."""
    if not _DATASET_NAME_PATTERN.fullmatch(dataset_name):
        raise ValueError(
            f"invalid dataset name {dataset_name!r}: "
            "use letters, digits, '-' or '_' (no path separators)"
        )
    return Path(schema_dir) / f"{dataset_name}.py"


def _load_schema_module(path: Path) -> Any:
    """Import the checked-in schema file and return its module-level `schema`."""
    spec = importlib.util.spec_from_file_location(
        f"ds_audit_toolkit_schemas.{path.stem}", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load schema module from {path}")
    module = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        spec.loader.exec_module(module)
    schema = getattr(module, "schema", None)
    if schema is None:
        raise ValueError(
            f"schema module at {path} defines no module-level `schema`; keep the "
            "`schema = ...` assignment when hand-editing the drafted file"
        )
    return schema


def _format_failures(failure_cases: pd.DataFrame) -> list[str]:
    """Render pandera failure_cases as short "column: check (N rows)" strings."""
    failures: list[str] = []
    column_cases = failure_cases[failure_cases["column"].notna()]
    grouped = column_cases.groupby(["column", "check"]).size()
    for (column, check), count in grouped.items():
        failures.append(f"{column}: {check} ({count} rows)")
    schema_cases = failure_cases[failure_cases["column"].isna()]
    grouped = schema_cases.groupby(["check", "failure_case"]).size()
    for (check, case), count in grouped.items():
        failures.append(f"{check}: {case} ({count} rows)")
    return failures


def draft_schema(
    df: Any, dataset_name: str, schema_dir: str = "config/schemas"
) -> SchemaValidationResult:
    """Infer dtype, nullability, and range checks; write a pandera schema file.

    First run against a new dataset infers via pandera.schema_inference and
    writes <schema_dir>/<dataset>.py via pandera.io to_script(). The drafted
    file is meant to be hand-edited and version-controlled: re-drafting
    overwrites it in place, so drafting stays an explicit, reviewable
    action — enforcement never regenerates the schema behind the user's
    back.
    """
    path = _schema_path(dataset_name, schema_dir)
    schema = infer_schema(df)
    schema.strict = True
    schema.coerce = False
    path.parent.mkdir(parents=True, exist_ok=True)
    to_script(schema, path_or_buf=path)
    return SchemaValidationResult(
        dataset=dataset_name, passed=True, failures=[], schema_path=str(path)
    )


def validate(
    df: Any, dataset_name: str, schema_dir: str = "config/schemas"
) -> SchemaValidationResult:
    """Enforce the checked-in (hand-editable, version-controlled) schema.

    Loads <schema_dir>/<dataset>.py and runs schema.validate(df, lazy=True);
    lazy mode collects ALL failure cases at once into one SchemaErrors,
    rendered as short "column: check (N rows)" strings. Never regenerates
    the schema blindly: raises FileNotFoundError pointing at draft_schema
    when no schema has been checked in yet.
    """
    path = _schema_path(dataset_name, schema_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"no checked-in schema for dataset '{dataset_name}' at {path}; run "
            "draft_schema first — schemas are never regenerated blindly"
        )
    schema = _load_schema_module(path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        return SchemaValidationResult(
            dataset=dataset_name,
            passed=False,
            failures=_format_failures(exc.failure_cases),
            schema_path=str(path),
        )
    return SchemaValidationResult(
        dataset=dataset_name, passed=True, failures=[], schema_path=str(path)
    )
