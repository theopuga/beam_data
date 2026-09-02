"""Tests for report rendering: html, markdown, unknown formats, empty sections."""

import pytest

from ds_audit_toolkit.reporting import render_report
from ds_audit_toolkit.types import (
    FeatureFlagReport,
    FlagEntry,
    JoinAuditResult,
    KeyQualityReport,
    SchemaValidationResult,
    StageResult,
)


def full_run_results():
    return {
        "run_id": "abc123",
        "config_path": "config/audit.yaml",
        "stages": [
            StageResult(stage="connect:clients", status="ok"),
            StageResult(stage="standardize:clients", status="ok"),
            StageResult(stage="join_audit", status="error", error="boom"),
        ],
        "join_audit": JoinAuditResult(
            match_rate=0.75,
            match_threshold=0.95,
            matched_rows=3,
            unmatched_keys=["d", "e"],
            column_mismatch_rates={"amt": 1 / 3},
            key_quality=KeyQualityReport(
                duplicates={"left": 0, "right": 1},
                nulls={"left": 2, "right": 0},
                dtype_mismatches=["id: object (left) vs int64 (right)"],
            ),
            fuzzy_used=True,
            fuzzy_confidence={"d": 0.91},
        ),
        "schema_validation": SchemaValidationResult(
            dataset="audit",
            passed=False,
            failures=["count: less_than_or_equal_to 3 (1 rows)"],
            schema_path="config/schemas/audit.py",
        ),
        "feature_flags": FeatureFlagReport(
            target_column="churn",
            flags=[
                FlagEntry(column="clean_col", leak_score=0.1, predictive_score=0.4, reason=""),
                FlagEntry(
                    column="leaky_col", leak_score=1.0, predictive_score=0.9, reason="correlation"
                ),
            ],
        ),
    }


def test_render_html(tmp_path):
    output = tmp_path / "out.html"
    returned = render_report(full_run_results(), str(output))
    assert returned == str(output)
    text = output.read_text(encoding="utf-8")
    assert "abc123" in text
    assert "config/audit.yaml" in text
    assert "connect:clients" in text
    assert "boom" in text
    assert "75.0" in text
    assert "95.0" in text
    assert "matched rows 3" in text
    assert "d, e" in text
    assert "amt" in text and "33.3" in text
    assert "id: object (left) vs int64 (right)" in text
    assert "left=0" in text and "right=1" in text
    assert "0.910" in text
    assert "count: less_than_or_equal_to 3 (1 rows)" in text
    assert text.index("leaky_col") < text.index("clean_col")


def test_render_markdown(tmp_path):
    output = tmp_path / "out.md"
    returned = render_report(full_run_results(), str(output), fmt="markdown")
    assert returned == str(output)
    text = output.read_text(encoding="utf-8")
    assert "# Audit run abc123" in text
    assert "| connect:clients | ok |  |" in text
    assert "| join_audit | error | boom |" in text
    assert "- match rate: 75.0% (threshold 95.0%)" in text
    assert "- unmatched keys (sample): d, e" in text
    assert "- fuzzy fallback used: yes" in text
    assert "- count: less_than_or_equal_to 3 (1 rows)" in text
    assert "| leaky_col | 1.00 | 0.90 | correlation |" in text
    assert text.index("leaky_col") < text.index("clean_col")


def test_unknown_format_raises(tmp_path):
    with pytest.raises(ValueError, match="rst"):
        render_report({"run_id": "x", "config_path": "c"}, str(tmp_path / "out.rst"), fmt="rst")
    assert not (tmp_path / "out.rst").exists()


def test_all_sections_empty_renders(tmp_path):
    results = {
        "run_id": "empty1",
        "config_path": "config/x.yaml",
        "stages": [],
        "join_audit": None,
        "schema_validation": None,
        "feature_flags": None,
    }
    output = tmp_path / "out.html"
    assert render_report(results, str(output)) == str(output)
    text = output.read_text(encoding="utf-8")
    assert "empty1" in text
    assert "No stages recorded." in text
    assert "No join audit for this run." in text
    assert "No schema validation for this run." in text
    assert "No feature flags for this run." in text
    markdown = tmp_path / "out.md"
    render_report(results, str(markdown), fmt="markdown")
    assert "No join audit for this run." in markdown.read_text(encoding="utf-8")


def test_feature_flags_absent_vs_empty(tmp_path):
    results = dict(full_run_results())
    results["feature_flags"] = FeatureFlagReport(target_column="churn", flags=[])
    render_report(results, str(tmp_path / "out.html"))
    assert "No feature flags for this run." in (tmp_path / "out.html").read_text(
        encoding="utf-8"
    )
