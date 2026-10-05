from __future__ import annotations

import copy
import hashlib
import json

import pytest

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.broker.client import BrokerTaskClient
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.common import sha256_json
from local_ai_lab.evaluation.cascade import SemanticEvaluationConfig, verify_evaluation_report
from local_ai_lab.evaluation.recalculate import recalculate_strategy_report
from local_ai_lab.strategies.executor import StrategySuiteExecutor
from local_ai_lab.training.results import RESULT_CONTRACT_VERSION
from test_system1_evaluation import MODEL, Transport


def test_job_executor_verified_artifact_persistence_and_reevaluation(tmp_path, monkeypatch):
    service = CoordinatorService(tmp_path / "coordinator.db")
    code = service.create_pairing_code()
    service.pair_and_register(pairing_code=code, node_id="worker", hostname="worker")
    service.record_product_item(
        record_id="broker-check", category="experiment", title="Broker", status="CAPABILITIES_SATISFIED",
        artifact_sha256="c" * 64, summary={"phase": "retrieval", "endpoint": "http://127.0.0.1:8000"},
    )
    inputs = service._execution_inputs(benchmark_id=None, snapshot_id=None, index_id=None, k=1)
    monkeypatch.setattr(service, "_execution_inputs", lambda **_: inputs)
    config = SemanticEvaluationConfig(enabled=True, shadow_mode=False, strong_judge_model=MODEL)
    record = service.create_strategy_suite_job(
        strategy_id="B0", broker_check_id="broker-check", broker_endpoint="http://127.0.0.1:8000",
        node_id="worker", target_model=MODEL, embedding_model=None, embedding_model_fingerprint=None,
        device="cpu", training_job_id=None, k=1, idempotency_key="system1-integration",
        evaluation=config.model_dump(),
    )
    job = service.repository.job(record["record_id"])
    spec = json.loads(job["spec_json"])
    assert spec["payload"]["evaluation"] == config.model_dump()
    assert record["summary"]["evaluation"] == config.model_dump()
    transport = Transport(capabilities={"system1_judgments": True, "system1_evaluation": True})
    monkeypatch.setattr("local_ai_lab.strategies.executor.BrokerTaskClient", lambda **kwargs: BrokerTaskClient(**kwargs, transport=transport))
    payload = {**spec["payload"], "resolved_snapshot": str(inputs["snapshot_path"]),
               "resolved_suite": str(inputs["suite_root"]), "resolved_index": str(inputs["index_path"]),
               "report_dir": str(tmp_path / "strategy-output")}
    result = StrategySuiteExecutor()(payload, lambda _: None)
    report_path = tmp_path / "strategy-output/strategy-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    count = len(inputs["case_ids"])
    assert result["evaluation_metrics"]["origins"]["system1"] == count
    assert report["quality"] == {"deterministic_pass_rate": 0}
    assert result["formal_status"] == "unverified"
    assert len(result["review_candidates"]) == count
    assert result["cost_amount"] is None
    verify_evaluation_report(report, config.model_dump())
    broken = copy.deepcopy(report)
    broken["evaluation_metrics"]["origins"]["system1"] += 1
    with pytest.raises(ValueError, match="metrics differ"):
        verify_evaluation_report(broken, config.model_dump())
    archive, _ = deterministic_zip(tmp_path / "strategy-output", tmp_path / "strategy-output.zip")
    artifact = service.artifacts.ingest_file(archive)
    uploaded = {**result, "artifacts": [{"kind": "strategy_suite_report", **artifact}]}
    monkeypatch.setattr(service.repository, "authorize_artifact_upload", lambda **_: None)
    service._validate_success_result(job, uploaded)
    # Completion records the validation version before finalizing product data.
    with service.repository.transaction() as db:
        db.execute("UPDATE jobs SET state='succeeded',result_validation_version=? WHERE job_id=?",
                   (RESULT_CONTRACT_VERSION, job["job_id"]))
    service._finalize_product_job(job["job_id"], outcome="succeeded", payload=uploaded)
    stored = service.repository.product_record(job["job_id"])
    assert stored["summary"]["evaluation_metrics"] == report["evaluation_metrics"]
    assert stored["summary"]["evaluation_configuration_fingerprint"] == sha256_json(config.model_dump())
    assert stored["summary"]["formal_status"] == "unverified"
    reviews = service.reviews()
    assert len(reviews) == count
    assert all(review["status"] == "draft" and review["training_state"] == "excluded" for review in reviews)
    recalculated = recalculate_strategy_report(
        report_path=report_path, suite_root=inputs["suite_root"], snapshot=inputs["snapshot_path"],
        config=config, client=BrokerTaskClient(endpoint="http://127.0.0.1:8000", token=None, transport=Transport()),
    )
    assert recalculated["source_report_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert recalculated["evaluation_metrics"]["origins"] == report["evaluation_metrics"]["origins"]
    assert recalculated["evaluation_metrics"]["gold"]["agreement"] is None
    assert all(row["evaluation"]["label"] == "correct" for row in recalculated["results"])
    invalid_report = {**report, "snapshot_hash": "0" * 64}
    bad_path = tmp_path / "bad-report.json"
    bad_path.write_text(json.dumps(invalid_report), encoding="utf-8")
    with pytest.raises(ValueError, match="exact frozen"):
        recalculate_strategy_report(report_path=bad_path, suite_root=inputs["suite_root"],
                                    snapshot=inputs["snapshot_path"], config=config,
                                    client=BrokerTaskClient(endpoint="http://127.0.0.1:8000", token=None))


def test_disabled_executor_preserves_old_report_and_does_not_call_system1(tmp_path, monkeypatch):
    service = CoordinatorService(tmp_path / "coordinator.db")
    inputs = service._execution_inputs(benchmark_id=None, snapshot_id=None, index_id=None, k=1)
    transport = Transport()
    monkeypatch.setattr("local_ai_lab.strategies.executor.BrokerTaskClient", lambda **kwargs: BrokerTaskClient(**kwargs, transport=transport))
    result = StrategySuiteExecutor()({
        "strategy_id": "B0", "broker_endpoint": "http://127.0.0.1:8000", "target_model": MODEL,
        "correlation_id": "off", "resolved_snapshot": str(inputs["snapshot_path"]),
        "resolved_suite": str(inputs["suite_root"]), "resolved_index": str(inputs["index_path"]),
        "report_dir": str(tmp_path / "off-output"),
    }, lambda _: None)
    report = json.loads((tmp_path / "off-output/strategy-report.json").read_text(encoding="utf-8"))
    assert "evaluation" not in result and "evaluation_metrics" not in report
    assert all("evaluation" not in row for row in report["results"])
    assert not any(c[1].endswith("/system1/judge") for c in transport.calls)
    verify_evaluation_report(report, None)


@pytest.mark.parametrize("raw", ["not json", "[]", '{"label":"correct"}'])
def test_invalid_structured_generation_fails_deterministically_before_system1(tmp_path, monkeypatch, raw):
    service = CoordinatorService(tmp_path / "coordinator.db")
    inputs = service._execution_inputs(benchmark_id=None, snapshot_id=None, index_id=None, k=1)
    transport = Transport(assistant_content=raw)
    monkeypatch.setattr("local_ai_lab.strategies.executor.BrokerTaskClient", lambda **kwargs: BrokerTaskClient(**kwargs, transport=transport))
    result = StrategySuiteExecutor()({
        "strategy_id": "B1", "broker_endpoint": "http://127.0.0.1:8000", "target_model": MODEL,
        "correlation_id": "invalid", "resolved_snapshot": str(inputs["snapshot_path"]),
        "resolved_suite": str(inputs["suite_root"]), "resolved_index": str(inputs["index_path"]),
        "report_dir": str(tmp_path / "invalid-output"), "evaluation": {"enabled": True},
    }, lambda _: None)
    assert result["evaluation_metrics"]["origins"]["deterministic"] == len(inputs["case_ids"])
    assert not any(c[1].endswith("/system1/judge") for c in transport.calls)
    report = json.loads((tmp_path / "invalid-output/strategy-report.json").read_text(encoding="utf-8"))
    assert all(row["evaluation"]["label"] == "incorrect" for row in report["results"])
