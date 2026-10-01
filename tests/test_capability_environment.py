from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.jobs import JobSpec
from result_fixtures import preflight_inputs, preflight_package


def worker(service: CoordinatorService) -> str:
    result = service.pair_and_register(
        pairing_code=service.create_pairing_code(), node_id="worker", hostname="worker",
    )
    return result["device_token"]


def report(backend: str = "cuda", *, driver: str = "1", temperature: int = 40) -> dict:
    return {
        "schema_version": "1.0", "observed_at": "2026-10-01T00:00:00Z",
        "facts": [
            {"key": "gpu.backend", "value": backend, "status": "detected"},
            {"key": "gpu.0.driver_version", "value": driver, "status": "detected"},
            {"key": "runtime.python", "value": "Python 3.13.0", "status": "detected"},
            {"key": "gpu.0.temperature_c", "value": temperature, "status": "detected"},
            {"key": "storage.free_bytes", "value": 123, "status": "detected"},
        ],
        "workloads": [],
    }


def verified_training(service: CoordinatorService) -> None:
    service.repository.record_capability_facts(
        "worker", facts=[
            {"key": "gpu.backend", "value": "cuda", "status": "tested"},
            {"key": "dtype.bf16", "value": True, "status": "tested"},
        ], source="training.preflight.v1",
    )
    service.repository.record_workload_evidence(
        "worker", kind="training.lora", status="tested", evidence_sha256="a" * 64,
    )


def capabilities(service: CoordinatorService) -> dict:
    return json.loads(service.repository.node_record("worker")["capabilities_json"])


def training_job(service: CoordinatorService) -> JobSpec:
    spec = JobSpec(kind="training.lora.v1", payload={}, requirements={
        "required_facts": {"gpu.backend": "cuda", "dtype.bf16": True},
        "required_workloads": ["training.lora"],
    })
    service.submit_job(spec, f"submit:{spec.job_id}")
    return spec


def test_changed_backend_invalidates_old_evidence_and_blocks_training(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(service)
    training_job(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report("rocm"))

    facts = {item["key"]: item for item in capabilities(service)["facts"]}
    assert facts["gpu.backend"]["value"] == "rocm"
    assert service.repository.overview()["nodes"][0]["tested_workloads"] == []
    assert service.claim_job(node_id="worker", token=token, idempotency_key="claim") is None


def test_driver_change_requires_new_preflight_even_when_backend_is_unchanged(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(service)
    spec = training_job(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report(driver="2"))

    assert service.claim_job(node_id="worker", token=token, idempotency_key="old-proof") is None
    verified_training(service)
    assert service.claim_job(node_id="worker", token=token, idempotency_key="new-proof")["job_id"] == spec.job_id


def test_fresh_timestamp_and_temperature_preserve_verified_training(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(service)
    spec = training_job(service)
    updated = report(temperature=60)
    updated["observed_at"] = "2026-10-01T01:00:00Z"
    updated["facts"][-1]["value"] = 789
    service.heartbeat(node_id="worker", token=token, capabilities=updated)

    assert service.repository.overview()["nodes"][0]["tested_workloads"] == ["training.lora"]
    assert service.claim_job(node_id="worker", token=token, idempotency_key="claim")["job_id"] == spec.job_id


def test_probe_without_ml_facts_preserves_facts_proved_by_preflight(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token = worker(service)
    observed = report()
    # NodeProbe observes driver/hardware; it does not run torch or prove a backend/dtype.
    observed["facts"] = [item for item in observed["facts"] if item["key"] != "gpu.backend"]
    service.heartbeat(node_id="worker", token=token, capabilities=observed)
    verified_training(service)
    spec = training_job(service)
    service.heartbeat(node_id="worker", token=token, capabilities=observed)
    assert service.claim_job(node_id="worker", token=token, idempotency_key="claim")["job_id"] == spec.job_id


@pytest.mark.parametrize("change", ["missing", "version", "partial", "repaired"])
def test_environment_changes_survive_coordinator_restart(tmp_path: Path, change: str) -> None:
    path = tmp_path / "coordinator.db"
    service = CoordinatorService(path)
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(service)
    spec = training_job(service)
    updated = report()
    if change == "missing":
        updated["facts"] = [item for item in updated["facts"] if item["key"] != "runtime.python"]
    elif change == "version":
        updated["facts"][2]["value"] = "Python 3.14.0"
    elif change == "partial":
        updated = {"facts": [{"key": "gpu.0.driver_version", "value": "2", "status": "detected"}]}
    else:
        repaired = service.pair_and_register(pairing_code=service.create_pairing_code(), node_id="worker", hostname="other")
        assert service.repository.node_record("worker")["capabilities_json"] is None
        token = repaired["device_token"]
    service.heartbeat(node_id="worker", token=token, capabilities=updated)

    service = CoordinatorService(path)
    assert service.claim_job(node_id="worker", token=token, idempotency_key="old-proof") is None
    verified_training(service)
    assert service.claim_job(node_id="worker", token=token, idempotency_key="new-proof")["job_id"] == spec.job_id


def test_repeated_self_report_does_not_restore_invalidated_proof(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(service)
    training_job(service)
    updated = report(driver="2")
    updated["facts"].extend([
        {"key": "dtype.bf16", "value": True, "status": "tested"},
    ])
    updated["workloads"] = [{"kind": "training.lora", "status": "benchmarked", "evidence_sha256": "a" * 64}]
    for _ in range(2):
        service.heartbeat(node_id="worker", token=token, capabilities=updated)
    assert service.claim_job(node_id="worker", token=token, idempotency_key="claim") is None
    overview = service.repository.overview()["nodes"][0]
    assert overview["tested_workloads"] == []
    assert "preflight" in overview["capability_warning"]
    verified_training(service)
    assert service.repository.overview()["nodes"][0]["capability_warning"] is None


def test_late_job_evidence_cannot_revalidate_an_environment_that_changed_back(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(service)
    spec = training_job(service)
    lease = service.claim_job(node_id="worker", token=token, idempotency_key="claim")
    generation = service.repository.job(spec.job_id)["environment_generation"]
    service.heartbeat(node_id="worker", token=token, capabilities=report("rocm"))
    service.heartbeat(node_id="worker", token=token, capabilities=report())

    assert not service.repository.record_workload_evidence(
        "worker", kind="training.lora", status="benchmarked", evidence_sha256="b" * 64,
        expected_environment_generation=generation,
    )
    assert not service.repository.record_capability_facts(
        "worker", facts=[{"key": "dtype.bf16", "value": True, "status": "tested"}],
        source="training.preflight.v1", expected_environment_generation=generation,
    )
    assert service.repository.overview()["nodes"][0]["tested_workloads"] == []
    assert lease is not None


def test_legacy_database_preserves_outputs_but_requires_new_capability_proof(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    service = CoordinatorService(path)
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(service)
    spec = training_job(service)
    with service.repository.transaction() as db:
        db.execute("ALTER TABLE jobs DROP COLUMN environment_generation")
        db.execute("ALTER TABLE nodes DROP COLUMN environment_generation")
    reopened = CoordinatorService(path)
    assert reopened.repository.job(spec.job_id)["state"] == "ready"
    assert reopened.repository.node_record("worker")["auth_token_hash"] == service.repository.node_record("worker")["auth_token_hash"]
    assert reopened.repository.overview()["nodes"][0]["tested_workloads"] == []
    assert reopened.claim_job(node_id="worker", token=token, idempotency_key="legacy-proof") is None
    reopened.heartbeat(node_id="worker", token=token, capabilities=report())
    verified_training(reopened)
    assert reopened.claim_job(node_id="worker", token=token, idempotency_key="new-proof")["job_id"] == spec.job_id


@pytest.mark.parametrize("change_timing", ["before_result", "during_publication", "after_result"])
def test_completed_preflight_is_invalidated_even_if_publication_races_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_timing: str,
) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token = worker(service)
    service.heartbeat(node_id="worker", token=token, capabilities=report())
    spec = JobSpec(kind="training.preflight.v1", payload=preflight_inputs())
    service.submit_job(spec, "submit")
    service.record_product_item(
        record_id=spec.job_id, category="training", title="Synthetic preflight publication",
        status="PREFLIGHT_QUEUED", artifact_sha256="a" * 64, summary={},
    )
    lease = service.claim_job(node_id="worker", token=token, idempotency_key="claim")
    service.ack_job(
        node_id="worker", token=token, job_id=spec.job_id, lease_token=lease["lease_token"],
        lease_generation=lease["lease_generation"], idempotency_key="ack",
    )
    def change_environment() -> None:
        service.heartbeat(node_id="worker", token=token, capabilities=report(driver="2"))
    if change_timing == "before_result":
        change_environment()
    elif change_timing == "during_publication":
        publish = service.repository.record_product_item
        def racing_publication(**item):
            change_environment()
            return publish(**item)
        monkeypatch.setattr(service.repository, "record_product_item", racing_publication)
    result = service.complete_job(
        node_id="worker", token=token, job_id=spec.job_id, attempt_id=lease["attempt_id"],
        lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
        outcome="succeeded", payload=preflight_package(service, lease, tmp_path / "result"), idempotency_key="complete",
    )
    if change_timing == "after_result":
        assert service.repository.product_record(spec.job_id)["status"] == "PREFLIGHT_PASSED"
        change_environment()
    assert result["accepted"] is True  # Historical output remains recoverable.
    assert service.repository.overview()["nodes"][0]["tested_workloads"] == []
    record = service.repository.product_record(spec.job_id)
    assert record["status"] == "PREFLIGHT_ENVIRONMENT_CHANGED"
    assert record["summary"]["capabilities_validated"] is False
