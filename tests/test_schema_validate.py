"""Tests for schema validation: drafting, enforcement, and failure reporting."""

import pandas as pd
import pytest

from ds_audit_toolkit.schema_validate import draft_schema, validate


def make_df():
    return pd.DataFrame(
        {
            "name": ["a", "b", "c"],
            "count": [1, 2, 3],
            "score": [1.5, 2.5, 3.5],
            "note": ["x", None, "z"],
        }
    )


def test_draft_then_validate_roundtrip(tmp_path):
    df = make_df()
    draft = draft_schema(df, "roundtrip_ds", schema_dir=str(tmp_path))
    assert draft.passed is True
    assert draft.failures == []
    assert draft.dataset == "roundtrip_ds"
    assert draft.schema_path == str(tmp_path / "roundtrip_ds.py")
    schema_file = tmp_path / "roundtrip_ds.py"
    assert schema_file.exists()
    text = schema_file.read_text(encoding="utf-8")
    assert "schema = DataFrameSchema(" in text
    assert "strict=True" in text
    assert "coerce=True" not in text
    outcome = validate(df, "roundtrip_ds", schema_dir=str(tmp_path))
    assert outcome.passed is True
    assert outcome.failures == []
    assert outcome.schema_path == draft.schema_path


def test_validate_reports_mutated_df(tmp_path):
    df = make_df()
    draft_schema(df, "mutated_ds", schema_dir=str(tmp_path))
    bad = df.copy()
    bad["score"] = bad["score"].astype(object)
    bad.loc[1, "score"] = "oops"
    bad.loc[0, "count"] = 999
    bad["surprise"] = 1
    outcome = validate(bad, "mutated_ds", schema_dir=str(tmp_path))
    assert outcome.passed is False
    assert outcome.failures
    assert all(isinstance(failure, str) for failure in outcome.failures)
    assert all(" rows)" in failure for failure in outcome.failures)
    assert any(failure.startswith("score: dtype") for failure in outcome.failures)
    assert any(failure.startswith("count: less_than_or_equal_to") for failure in outcome.failures)
    assert any("column_in_schema" in failure and "surprise" in failure for failure in outcome.failures)


def test_validate_without_draft_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="draft_schema"):
        validate(make_df(), "never_drafted", schema_dir=str(tmp_path))
    assert not (tmp_path / "never_drafted.py").exists()


@pytest.mark.parametrize("name", ["../escape", "ds;drop", "has space", "", ".hidden"])
def test_invalid_dataset_name_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="invalid dataset name"):
        draft_schema(make_df(), name, schema_dir=str(tmp_path))
    with pytest.raises(ValueError, match="invalid dataset name"):
        validate(make_df(), name, schema_dir=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_dataset_name_with_hyphen_and_underscore_allowed(tmp_path):
    draft = draft_schema(make_df(), "my-dataset_v2", schema_dir=str(tmp_path))
    assert (tmp_path / "my-dataset_v2.py").exists()
    outcome = validate(make_df(), "my-dataset_v2", schema_dir=str(tmp_path))
    assert outcome.passed is True
    assert draft.dataset == "my-dataset_v2"
