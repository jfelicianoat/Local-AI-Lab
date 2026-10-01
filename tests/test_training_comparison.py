from __future__ import annotations

import pytest
import json
import hashlib
import zipfile

from local_ai_lab.coordinator.service import CoordinatorService

from local_ai_lab.training.comparison import (
    compare_verification_gain, require_same_task, verified_pass_rate,
)


def _comparison(strategy: str = "F2") -> dict:
    baseline_strategy = "R4" if strategy == "F2" else "B1"
    baseline = {
        "strategy_id": baseline_strategy, "suite_fingerprint": "suite", "snapshot_hash": "snapshot",
        "snapshot_id": "snapshot-id", "case_ids": ["a", "b"], "benchmark_id": "benchmark",
        "index_id": "index", "k": 5, "embedding_model": "embed" if strategy == "F2" else None,
        "embedding_model_fingerprint": "fingerprint" if strategy == "F2" else None,
        "target_model": {"model": "base"},
    }
    training = {
        "evaluation_strategy_id": strategy, "baseline_suite_fingerprint": "suite",
        "baseline_snapshot_hash": "snapshot", "baseline_case_ids": ["a", "b"],
    }
    return dict(
        strategy_id=strategy, training=training, baseline=baseline,
        execution={key: baseline[key] for key in ("suite_fingerprint", "snapshot_hash", "snapshot_id", "case_ids")},
        benchmark_id="benchmark", index_id="index", embedding_model=baseline["embedding_model"],
        embedding_model_fingerprint=baseline["embedding_model_fingerprint"],
        k=5, expected_baseline_model="base",
    )


@pytest.mark.parametrize("strategy", ["F1", "F2"])
def test_trained_evaluation_reuses_its_baseline_task(strategy: str) -> None:
    valid = _comparison(strategy)
    require_same_task(**valid)
    for change in (
        {"execution": {**valid["execution"], "case_ids": ["different"]}},
        {"execution": {**valid["execution"], "snapshot_hash": "changed"}},
        {"baseline": {**valid["baseline"], "strategy_id": "B0"}},
        {"benchmark_id": "other"},
        {"expected_baseline_model": "other"},
        {"k": 6},
    ):
        with pytest.raises(ValueError):
            require_same_task(**{**valid, **change})
    if strategy == "F2":
        with pytest.raises(ValueError, match="retrieval configuration"):
            require_same_task(**{**valid, "embedding_model_fingerprint": "other"})


def test_verification_gain_is_measured_from_cases_and_keeps_its_scope() -> None:
    report = {
        "schema_version": "strategy-suite-report.v1", "results": [
            {"case_id": "a", "verification": {"deterministic_pass": True}},
            {"case_id": "b", "verification": {"deterministic_pass": False}},
        ],
        "quality": {"deterministic_pass_rate": 0.5}, "latency_ms": 120.0,
    }
    assert verified_pass_rate(report, ["a", "b"]) == 0.5
    assert compare_verification_gain(0.25, 0.5, 0.2)["target_met"] is True
    assert compare_verification_gain(0.5, 0.25, 0.2)["target_met"] is False
    assert "not_answer_fidelity" in compare_verification_gain(0.25, 0.5, 0.2)["scope"]
    with pytest.raises(ValueError, match="pass rate differs"):
        verified_pass_rate({**report, "quality": {"deterministic_pass_rate": 1.0}}, ["a", "b"])
    with pytest.raises(ValueError, match="results differ"):
        verified_pass_rate(report, ["b", "a"])


def test_completed_adapter_evaluation_records_gain_without_promoting(tmp_path) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    service.record_product_item(
        record_id="training-1", category="training", title="LoRA", status="TRAINING_SUCCEEDED",
        artifact_sha256="a" * 64, summary={
            "baseline_experiment_id": "baseline-1", "baseline_verified_quality": 0.5,
            "minimum_quality_gain": 0.1, "validation_status": "pending_post_training_evaluation",
        },
    )
    for job_id, observed in (("evaluation-1", 0.65), ("evaluation-2", 0.55)):
        with service.repository.transaction() as db:
            db.execute(
                "INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,created_at,updated_at,result_validation_version) "
                "VALUES(?,?,?,?,?,?,1)",
                (job_id, json.dumps({"kind": "strategy.suite.v1"}), "fingerprint", "succeeded",
                 "2026-09-29", "2026-09-29"),
            )
        service.record_product_item(
            record_id=job_id, category="experiment", title="F1", status="EXPERIMENT_QUEUED",
            artifact_sha256="b" * 64, summary={"strategy_id": "F1", "training_job_id": "training-1"},
        )
        service._finalize_product_job(job_id, outcome="succeeded", payload={
            "strategy_id": "F1", "quality": {"deterministic_pass_rate": observed},
        })
        evaluation = service.repository.product_record(job_id)
        training = service.repository.product_record("training-1")
        assert evaluation["summary"]["baseline_comparison"]["observed"] == observed
        assert training["summary"]["last_baseline_comparison"]["evaluation_experiment_id"] == job_id
        assert training["summary"]["promotion_status"] != "validated"
    assert training["summary"]["validation_status"] == "deterministic_target_not_met"
    assert training["summary"]["promotion_status"] == "experimental_not_promoted"


def test_legacy_adapter_evaluation_completes_without_claiming_a_gain(tmp_path) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    service.record_product_item(
        record_id="legacy-training", category="training", title="Older adapter",
        status="TRAINING_SUCCEEDED", artifact_sha256="a" * 64,
        summary={"baseline_experiment_id": "old-baseline"},
    )
    with service.repository.transaction() as db:
        db.execute(
            "INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,created_at,updated_at,result_validation_version) "
            "VALUES(?,?,?,?,?,?,1)",
            ("legacy-evaluation", json.dumps({"kind": "strategy.suite.v1"}), "fingerprint",
             "succeeded", "2026-09-29", "2026-09-29"),
        )
    service.record_product_item(
        record_id="legacy-evaluation", category="experiment", title="F1",
        status="EXPERIMENT_QUEUED", artifact_sha256="b" * 64,
        summary={"strategy_id": "F1", "training_job_id": "legacy-training"},
    )
    service._finalize_product_job(
        "legacy-evaluation", outcome="succeeded",
        payload={"strategy_id": "F1", "quality": {"deterministic_pass_rate": 0.8}},
    )
    evaluation = service.repository.product_record("legacy-evaluation")
    training = service.repository.product_record("legacy-training")
    assert evaluation["summary"]["baseline_comparison"] == {
        "status": "unverifiable_legacy_baseline", "evaluation_experiment_id": "legacy-evaluation",
    }
    assert training["summary"]["validation_status"] == "unverifiable_legacy_baseline"
    assert training["summary"]["promotion_status"] == "experimental_not_promoted"


def test_strategy_completion_rejects_metrics_changed_outside_the_report(tmp_path, monkeypatch) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    report = {
        "schema_version": "strategy-suite-report.v1", "strategy_id": "F1",
        "suite_fingerprint": "suite", "snapshot_hash": "snapshot", "case_ids": ["a", "b"],
        "target_model": {"provider": "local_adapter", "deployment": "training", "model": "base"},
        "k": 5, "trained_model_identity": None,
        "results": [{"case_id": "a", "verification": {"deterministic_pass": True}},
                    {"case_id": "b", "verification": {"deterministic_pass": False}}],
        "quality": {"deterministic_pass_rate": 0.5}, "latency_ms": 120.0,
    }
    report_bytes = json.dumps(report).encode()
    archive = tmp_path / "report.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("strategy-report.json", report_bytes)
    artifact = service.artifacts.ingest_file(archive)
    service.record_product_item(
        record_id="evaluation", category="experiment", title="F1", status="EXPERIMENT_QUEUED",
        artifact_sha256="a" * 64, summary={key: report[key] for key in (
            "suite_fingerprint", "snapshot_hash", "case_ids", "strategy_id", "target_model", "k",
            "trained_model_identity",
        )},
    )
    monkeypatch.setattr(service.repository, "authorize_artifact_upload", lambda **_kwargs: None)
    job = {"job_id": "evaluation", "assigned_node_id": "worker", "spec_json": json.dumps({
        "kind": "strategy.suite.v1", "payload": {
            "collect_outputs": [{"kind": "strategy_suite_report"}],
        },
    })}
    payload = {
        "artifacts": [{"kind": "strategy_suite_report", "artifact_id": artifact["artifact_id"],
                       "sha256": artifact["sha256"], "size": artifact["size"]}],
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "suite_fingerprint": "suite", "snapshot_hash": "snapshot", "case_ids": ["a", "b"],
        "strategy_id": "F1", "quality": {"deterministic_pass_rate": 1.0}, "latency_ms": 120.0,
    }
    with pytest.raises(ValueError, match="metrics or model differ"):
        service._validate_success_result(job, payload)
    service._validate_success_result(job, {**payload, "quality": report["quality"]})
