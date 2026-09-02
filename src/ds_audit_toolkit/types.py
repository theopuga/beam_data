"""Shared stage contracts: every pipeline stage returns one of these artifacts."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageResult:
    """Outcome of one pipeline stage (status: ok | error | skipped)."""

    stage: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class KeyQualityReport:
    """Pre-join key checks: duplicates, nulls, dtype mismatches between sides."""

    duplicates: dict[str, int] = field(default_factory=dict)
    nulls: dict[str, int] = field(default_factory=dict)
    dtype_mismatches: list[str] = field(default_factory=list)


@dataclass
class JoinAuditResult:
    """Match report from join_audit (exact via datacompy, fuzzy fallback optional)."""

    match_rate: float
    match_threshold: float
    matched_rows: int
    unmatched_keys: list[str] = field(default_factory=list)
    column_mismatch_rates: dict[str, float] = field(default_factory=list)
    key_quality: KeyQualityReport | None = None
    fuzzy_used: bool = False
    fuzzy_confidence: dict[str, float] | None = None
    datacompy_report: dict | None = None


@dataclass
class SchemaValidationResult:
    """Outcome of pandera enforcement against the checked-in schema."""

    dataset: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    schema_path: str | None = None


@dataclass
class FlagEntry:
    """One feature's advisory verdict — analyst decides, nothing is auto-dropped."""

    column: str
    leak_score: float
    predictive_score: float
    reason: str


@dataclass
class FeatureFlagReport:
    """Per-feature flag table from feature_flags."""

    target_column: str
    flags: list[FlagEntry] = field(default_factory=list)


@dataclass
class RunReport:
    """Single artifact for one pipeline run: attachable to a PR or review."""

    run_id: str
    config_path: str
    stages: list[StageResult] = field(default_factory=list)
    join_audit: JoinAuditResult | None = None
    schema_validation: SchemaValidationResult | None = None
    feature_flags: FeatureFlagReport | None = None

    def save(self, output_path: str, fmt: str = "html") -> str:
        """Render via reporting (deferred import avoids a circular dependency)."""
        from ds_audit_toolkit.reporting.core import render_report

        return render_report(
            {
                "run_id": self.run_id,
                "config_path": self.config_path,
                "stages": self.stages,
                "join_audit": self.join_audit,
                "schema_validation": self.schema_validation,
                "feature_flags": self.feature_flags,
            },
            output_path,
            fmt,
        )
