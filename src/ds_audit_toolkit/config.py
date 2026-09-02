"""Pipeline config: typed representation of the YAML in config/.

One loader for the whole config (sources, join, target/time columns) — stages
consume typed dataclasses, never parse YAML themselves.
"""

from dataclasses import dataclass, field


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


def load_config(config_path: str) -> PipelineConfig:
    """Parse and validate a pipeline YAML file into a PipelineConfig."""
    raise NotImplementedError("config parsing lands in Phase 1")
