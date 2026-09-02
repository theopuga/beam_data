"""Pipeline config: typed representation of the YAML in config/.

One loader for the whole config (sources, join, target/time columns) — stages
consume typed dataclasses, never parse YAML themselves. `${VAR}` references
in values are expanded from the environment so secrets never need to live in
committed YAML files.
"""

import os
import re
from dataclasses import dataclass, field

import yaml


@dataclass
class SourceSpec:
    """One declared source; adding a source is a config line, not new code."""

    conn: str
    table: str
    key: str
    key_type: str


@dataclass
class JoinConfig:
    """Join audit settings.

    match_threshold below this triggers fuzzy fallback (0.95 placeholder per
    PLAN.md section 8). abs_tol/rel_tol pass through to datacompy PandasCompare;
    per-column tolerance dicts are the long-term form (PLAN.md section 6) and
    start as a flat default.
    """

    match_threshold: float = 0.95
    fuzzy_fallback: bool = True
    abs_tol: float = 0.0
    rel_tol: float = 0.0


@dataclass
class PipelineConfig:
    """Full pipeline config; target_column omitted => feature flagging is skipped."""

    sources: dict[str, SourceSpec] = field(default_factory=dict)
    join: JoinConfig = field(default_factory=JoinConfig)
    target_column: str | None = None
    time_column: str | None = None


_SOURCE_FIELDS = {"conn", "table", "key", "key_type"}
_JOIN_FIELDS = {"match_threshold", "fuzzy_fallback", "abs_tol", "rel_tol"}
_TOP_LEVEL_FIELDS = {"sources", "join", "target_column", "time_column"}
_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: str, ctx: str) -> str:
    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"{ctx}: environment variable {name!r} is not set")
        return os.environ[name]

    return _ENV_VAR.sub(repl, value)


def load_config(config_path: str) -> PipelineConfig:
    """Parse and validate a pipeline YAML file into a PipelineConfig.

    Strict validation: unknown or missing fields raise with the offending
    config path in the message — typo protection for a config-driven tool.
    """
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path}: top-level YAML must be a mapping")
    unknown = set(raw) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ValueError(f"{config_path}: unknown top-level fields {sorted(unknown)}")

    sources_raw = raw.get("sources") or {}
    if not isinstance(sources_raw, dict):
        raise ValueError(f"{config_path}: 'sources' must be a mapping")
    sources: dict[str, SourceSpec] = {}
    for name, spec in sources_raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"sources.{name}: must be a mapping")
        unknown = set(spec) - _SOURCE_FIELDS
        if unknown:
            raise ValueError(f"sources.{name}: unknown fields {sorted(unknown)}")
        missing = _SOURCE_FIELDS - set(spec)
        if missing:
            raise ValueError(f"sources.{name}: missing fields {sorted(missing)}")
        sources[name] = SourceSpec(
            conn=_expand_env(str(spec["conn"]), f"sources.{name}.conn"),
            table=str(spec["table"]),
            key=str(spec["key"]),
            key_type=str(spec["key_type"]),
        )
    if not sources:
        raise ValueError(f"{config_path}: 'sources' must declare at least one source")

    join_raw = raw.get("join") or {}
    if not isinstance(join_raw, dict):
        raise ValueError(f"{config_path}: 'join' must be a mapping")
    unknown = set(join_raw) - _JOIN_FIELDS
    if unknown:
        raise ValueError(f"{config_path}: unknown join fields {sorted(unknown)}")
    join = JoinConfig(
        match_threshold=float(join_raw.get("match_threshold", 0.95)),
        fuzzy_fallback=bool(join_raw.get("fuzzy_fallback", True)),
        abs_tol=float(join_raw.get("abs_tol", 0.0)),
        rel_tol=float(join_raw.get("rel_tol", 0.0)),
    )
    if not 0.0 <= join.match_threshold <= 1.0:
        raise ValueError(f"{config_path}: join.match_threshold must be in [0, 1]")

    return PipelineConfig(
        sources=sources,
        join=join,
        target_column=raw.get("target_column"),
        time_column=raw.get("time_column"),
    )
