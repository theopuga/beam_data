"""End-to-end orchestration: connect, standardize, join + audit, validate, flag.

Dependency direction is one-way:
    pipeline -> {connectors, standardize, join_audit, schema_validate,
                 feature_flags, reporting} -> {types, config}
Stages never import each other; they exchange dataclasses from types.py.
"""

from pathlib import Path
from uuid import uuid4

import pandas as pd
import sqlalchemy

from ds_audit_toolkit.config import load_config
from ds_audit_toolkit.connectors import get_table
from ds_audit_toolkit.feature_flags import flag_features
from ds_audit_toolkit.join_audit import audit_join
from ds_audit_toolkit.schema_validate import draft_schema, validate
from ds_audit_toolkit.standardize import standardize
from ds_audit_toolkit.types import RunReport, StageResult

_DOWNSTREAM_STAGES = ["join_audit", "schema_validate", "feature_flags"]
_CONNECT_ERRORS = (sqlalchemy.exc.SQLAlchemyError, OSError, ValueError, KeyError)
_STANDARDIZE_ERRORS = (KeyError, ValueError, TypeError)
_JOIN_ERRORS = (ValueError, TypeError, KeyError)
_SCHEMA_ERRORS = (OSError, ImportError, ValueError, TypeError)
_FLAG_ERRORS = (ValueError, TypeError, KeyError)


def _skip(run: RunReport, stage_names: list[str]) -> None:
    """Record stages that cannot run because an upstream artifact is missing."""
    for stage_name in stage_names:
        run.stages.append(StageResult(stage=stage_name, status="skipped"))


def run_audit(config_path: str) -> RunReport:
    """Run the full audit pipeline defined by a YAML config.

    Stages, in order:
        1. connect:<name> / standardize:<name> for every declared source,
           in config order (connectors, then standardize on the key column).
        2. join_audit on the FIRST TWO sources (v1 pairwise). Key column
           names may differ between the sides (e.g. postal_code vs fsa): the
           right frame's key column is renamed to the left frame's key name
           before auditing, so the join key aligns under one name.
        3. schema_validate on the joined frame (left.merge(right, on=key,
           how="inner")), dataset named after the config file stem. A missing
           checked-in schema is auto-drafted on first run (draft_schema, then
           re-validate); from then on validation never regenerates it.
        4. feature_flags on the joined frame, only when target_column is
           configured — otherwise the stage is recorded as skipped.

    A source that fails to load (connect or standardize) leaves no frame; if
    either of the first two sources is missing, the join and all downstream
    stages are recorded as skipped. A join_audit failure likewise skips the
    downstream stages. Every stage records ok/error/skipped in the report;
    each stage maps its realistic failure classes (connector, key, datacompy,
    pandera, flagging errors) to an error status, and anything outside those
    propagates to the caller.
    """
    cfg = load_config(config_path)
    run = RunReport(run_id=uuid4().hex, config_path=config_path)
    frames: dict[str, pd.DataFrame] = {}
    for name, spec in cfg.sources.items():
        try:
            df = get_table(spec.conn, spec.table)
            run.stages.append(StageResult(stage=f"connect:{name}", status="ok"))
        except _CONNECT_ERRORS as exc:
            run.stages.append(
                StageResult(stage=f"connect:{name}", status="error", error=str(exc))
            )
            continue
        try:
            df = standardize(df, spec.key, spec.key_type)
            run.stages.append(StageResult(stage=f"standardize:{name}", status="ok"))
        except _STANDARDIZE_ERRORS as exc:
            run.stages.append(
                StageResult(stage=f"standardize:{name}", status="error", error=str(exc))
            )
            continue
        frames[name] = df

    source_names = list(cfg.sources)
    if len(source_names) < 2 or any(name not in frames for name in source_names[:2]):
        _skip(run, _DOWNSTREAM_STAGES)
        return run

    left_name, right_name = source_names[0], source_names[1]
    left, right = frames[left_name], frames[right_name]
    key = cfg.sources[left_name].key
    right_key = cfg.sources[right_name].key
    if right_key != key:
        right = right.rename(columns={right_key: key})
    joined = left.merge(right, on=key, how="inner")

    try:
        run.join_audit = audit_join(
            left,
            right,
            key,
            match_threshold=cfg.join.match_threshold,
            fuzzy_fallback=cfg.join.fuzzy_fallback,
            abs_tol=cfg.join.abs_tol,
            rel_tol=cfg.join.rel_tol,
            left_name=left_name,
            right_name=right_name,
        )
        run.stages.append(StageResult(stage="join_audit", status="ok"))
    except _JOIN_ERRORS as exc:
        run.stages.append(
            StageResult(stage="join_audit", status="error", error=str(exc))
        )
        _skip(run, ["schema_validate", "feature_flags"])
        return run

    dataset_name = Path(config_path).stem
    try:
        try:
            run.schema_validation = validate(joined, dataset_name)
        except FileNotFoundError:
            draft_schema(joined, dataset_name)
            run.schema_validation = validate(joined, dataset_name)
        run.stages.append(StageResult(stage="schema_validate", status="ok"))
    except _SCHEMA_ERRORS as exc:
        run.stages.append(
            StageResult(stage="schema_validate", status="error", error=str(exc))
        )

    if cfg.target_column is None:
        run.stages.append(StageResult(stage="feature_flags", status="skipped"))
        return run
    try:
        run.feature_flags = flag_features(joined, cfg.target_column, cfg.time_column)
        run.stages.append(StageResult(stage="feature_flags", status="ok"))
    except _FLAG_ERRORS as exc:
        run.stages.append(
            StageResult(stage="feature_flags", status="error", error=str(exc))
        )
    return run
