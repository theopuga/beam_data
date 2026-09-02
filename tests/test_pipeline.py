"""End-to-end pipeline tests over sqlite fixtures plus report saving."""

import pandas as pd
import sqlalchemy
import yaml

import ds_audit_toolkit
from ds_audit_toolkit.pipeline import run_audit
from ds_audit_toolkit.types import RunReport

CLIENTS = pd.DataFrame({"client_id": ["C1", "C2", "C3"], "val": [1.0, 2.0, 3.0]})
REFS = pd.DataFrame({"client_id": ["C1", "C2", "C3"], "ref": ["x", "y", "z"]})


def make_db(tmp_path, clients=None, refs=None):
    conn = f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
    engine = sqlalchemy.create_engine(conn)
    (clients if clients is not None else CLIENTS).to_sql("clients", engine, index=False)
    (refs if refs is not None else REFS).to_sql("refs", engine, index=False)
    engine.dispose()
    return conn


def write_config(tmp_path, conn, refs_key="client_id", **extra):
    config = {
        "sources": {
            "clients": {
                "conn": conn,
                "table": "clients",
                "key": "client_id",
                "key_type": "client_id",
            },
            "refs": {
                "conn": conn,
                "table": "refs",
                "key": refs_key,
                "key_type": "client_id",
            },
        },
        "join": {"match_threshold": 0.95},
    }
    config.update(extra)
    path = tmp_path / "audit.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(path)


def test_package_imports():
    assert ds_audit_toolkit.__version__ == "0.1.0"


def test_run_audit_exported():
    assert callable(ds_audit_toolkit.run_audit)


def test_run_audit_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = make_db(tmp_path)
    config_path = write_config(tmp_path, conn)
    report = run_audit(config_path)
    assert isinstance(report, RunReport)
    assert len(report.run_id) == 32
    assert report.config_path == config_path
    statuses = {stage.stage: stage.status for stage in report.stages}
    assert statuses == {
        "connect:clients": "ok",
        "standardize:clients": "ok",
        "connect:refs": "ok",
        "standardize:refs": "ok",
        "join_audit": "ok",
        "schema_validate": "ok",
        "feature_flags": "skipped",
    }
    assert report.join_audit is not None
    assert report.join_audit.match_rate == 1.0
    assert report.join_audit.matched_rows == 3
    assert report.join_audit.fuzzy_used is False
    assert report.schema_validation is not None
    assert report.schema_validation.passed is True
    assert (tmp_path / "config" / "schemas" / "audit.py").exists()
    assert report.feature_flags is None

    output = tmp_path / "out.html"
    saved = report.save(str(output))
    assert saved == str(output)
    text = output.read_text(encoding="utf-8")
    assert report.run_id in text
    assert "match rate 100.0%" in text
    assert "threshold 95.0%" in text

    rerun = run_audit(config_path)
    assert rerun.schema_validation is not None
    assert rerun.schema_validation.passed is True
    assert rerun.schema_validation.failures == []


def test_run_audit_flags_features_when_target_set(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = make_db(
        tmp_path,
        refs=pd.DataFrame(
            {"client_id": ["C1", "C2", "C3"], "ref": ["x", "y", "z"], "churn": [0, 1, 0]}
        ),
    )
    config_path = write_config(tmp_path, conn, target_column="churn")
    report = run_audit(config_path)
    statuses = {stage.stage: stage.status for stage in report.stages}
    assert statuses["feature_flags"] == "ok"
    assert report.feature_flags is not None
    assert report.feature_flags.target_column == "churn"
    assert {flag.column for flag in report.feature_flags.flags} == {"client_id", "val", "ref"}


def test_run_audit_renames_right_key_to_left_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = make_db(
        tmp_path,
        refs=pd.DataFrame({"ref_id": ["C1", "C2", "C3"], "ref": ["x", "y", "z"]}),
    )
    config_path = write_config(tmp_path, conn, refs_key="ref_id")
    report = run_audit(config_path)
    statuses = {stage.stage: stage.status for stage in report.stages}
    assert statuses["standardize:refs"] == "ok"
    assert statuses["join_audit"] == "ok"
    assert report.join_audit is not None
    assert report.join_audit.match_rate == 1.0
    assert report.join_audit.matched_rows == 3


def test_run_audit_skips_downstream_when_source_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = make_db(tmp_path)
    broken_conn = f"sqlite:///{(tmp_path / 'missing.sqlite').as_posix()}"
    config = {
        "sources": {
            "clients": {
                "conn": broken_conn,
                "table": "clients",
                "key": "client_id",
                "key_type": "client_id",
            },
            "refs": {
                "conn": conn,
                "table": "refs",
                "key": "client_id",
                "key_type": "client_id",
            },
        }
    }
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    report = run_audit(str(path))
    statuses = {stage.stage: stage.status for stage in report.stages}
    assert statuses["connect:clients"] == "error"
    assert statuses["connect:refs"] == "ok"
    assert statuses["join_audit"] == "skipped"
    assert statuses["schema_validate"] == "skipped"
    assert statuses["feature_flags"] == "skipped"
    assert report.join_audit is None
    assert report.schema_validation is None
    assert report.feature_flags is None
    error_stage = next(stage for stage in report.stages if stage.stage == "connect:clients")
    assert error_stage.error
    assert not (tmp_path / "config").exists()
