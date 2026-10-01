from __future__ import annotations

import json
import zipfile
import hashlib
from pathlib import Path

import pytest

from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.exporting.package import ExportArtifact, ExportPackageBuilder
from result_fixtures import preflight_inputs, preflight_package, training_inputs, training_package


def started(service: CoordinatorService, *, inputs=None, kind="training.preflight.v1") -> tuple[str, dict]:
    registration = service.pair_and_register(
        pairing_code=service.create_pairing_code(), node_id="worker", hostname="worker",
    )
    token = registration["device_token"]
    spec = JobSpec(kind=kind, payload=inputs if inputs is not None else preflight_inputs())
    service.submit_job(spec, f"submit:{spec.job_id}")
    service.record_product_item(
        record_id=spec.job_id, category="training", title="Protocol fixture",
        status="PREFLIGHT_QUEUED", artifact_sha256=spec.fingerprint(), summary={},
    )
    lease = service.claim_job(node_id="worker", token=token, idempotency_key="claim")
    service.ack_job(node_id="worker", token=token, job_id=spec.job_id,
                    lease_token=lease["lease_token"], lease_generation=lease["lease_generation"], idempotency_key="ack")
    return token, lease


def finish(service, token, lease, result):
    return service.complete_job(node_id="worker", token=token, job_id=lease["job_id"], attempt_id=lease["attempt_id"],
                                lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
                                outcome="succeeded", payload=result, idempotency_key="complete")


def test_valid_preflight_and_response_replay_preserve_one_proof(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, lease = started(service)
    result = preflight_package(service, lease, tmp_path / "result")
    accepted = finish(service, token, lease, result)
    assert accepted["accepted"] is True
    assert finish(service, token, lease, result) == accepted
    assert service.repository.product_record(lease["job_id"])["status"] == "PREFLIGHT_PASSED"
    assert service.repository.overview()["nodes"][0]["tested_workloads"] == ["training.lora"]


def test_plain_file_cannot_prove_a_preflight(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, lease = started(service)
    source = tmp_path / "fake.bin"
    source.write_bytes(b"not a ZIP or a training manifest")
    stored = service.artifacts.ingest_file(source)
    service.repository.bind_artifact_upload(artifact_id=stored["artifact_id"], node_id="worker",
                                            job=service.repository.job(lease["job_id"]), sha256=stored["sha256"])
    with pytest.raises(ValueError):
        finish(service, token, lease, {"preflight_sha256": "b" * 64, "checks": {"invented": True},
                                      "backend": "cuda", "dtype": "bf16", "artifacts": [{"kind": "training_preflight", **stored}]})
    assert service.repository.job(lease["job_id"])["state"] == "acknowledged"
    assert service.repository.overview()["nodes"][0]["tested_workloads"] == []


@pytest.mark.parametrize("fault", [
    "schema", "contract_bool", "checks_empty", "checks_string", "loss_nan", "loss_increasing", "steps",
    "dataset", "model", "dtype", "config", "attempt", "file_hash", "manifest_hash", "payload_checks",
])
def test_invalid_preflight_cannot_publish_proof(tmp_path: Path, fault: str) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, lease = started(service)
    def corrupt(manifest):
        if fault == "schema": manifest["schema_version"] = "invented.v1"
        elif fault == "contract_bool": manifest["contract"]["c1_assistant_only_loss"] = "false"
        elif fault == "checks_empty": manifest["checks"] = {}
        elif fault == "checks_string": manifest["checks"]["reload"] = "true"
        elif fault == "loss_nan": manifest["losses"] = [float("nan"), 0.5]
        elif fault == "loss_increasing": manifest["losses"] = [0.5, 2.0]
        elif fault == "steps": manifest["resume_global_step"] = 20
        elif fault == "dataset": manifest["dataset_fingerprint"] = "b" * 64
        elif fault == "model": manifest["base_model"] = "other-model"
        elif fault == "dtype": manifest["dtype"] = "fp16"
        elif fault == "config": manifest["lora_config"] = {"rank": 32}
        elif fault == "attempt": manifest["source_attempt"]["source_attempt_id"] = "old-attempt"
        elif fault == "file_hash": manifest["files"][0]["sha256"] = "0" * 64
    def corrupt_result(result):
        if fault == "manifest_hash": result["preflight_sha256"] = "0" * 64
        elif fault == "payload_checks": result["checks"] = {"invented": True}
    result = preflight_package(service, lease, tmp_path / "result", mutate=corrupt, result_mutate=corrupt_result)
    with pytest.raises(ValueError):
        finish(service, token, lease, result)
    assert service.repository.job(lease["job_id"])["state"] == "acknowledged"
    assert service.repository.product_record(lease["job_id"])["status"] == "PREFLIGHT_QUEUED"
    assert service.repository.overview()["nodes"][0]["tested_workloads"] == []


def test_preflight_without_output_contract_cannot_promote_capabilities(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, lease = started(service, inputs={})
    with pytest.raises(ValueError):
        finish(service, token, lease, {"checks": {"load": True}, "backend": "cuda", "dtype": "bf16"})
    assert service.repository.overview()["nodes"][0]["tested_workloads"] == []


def export_package(service, lease, root):
    root.mkdir()
    data = root / "adapter.zip"
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("adapter_config.json", "{}")
        archive.writestr("adapter_model.safetensors", b"synthetic weights")
    job = service.repository.job(lease["job_id"])
    inputs = lease["spec"]["payload"]
    attempt = {"source_job_id": job["job_id"], "source_attempt_id": job["attempt_id"],
               "source_lease_generation": job["lease_generation"], "source_spec_sha256": job["spec_fingerprint"],
               "training_kind": lease["spec"]["kind"]}
    package = ExportPackageBuilder().build(
        [ExportArtifact("adapter", data, hashlib.sha256(data.read_bytes()).hexdigest(), inputs["license_id"], inputs["source_artifact_reference"])],
        root / "packages", source_training_manifest_sha256=inputs["source_training_manifest_sha256"],
        serving=inputs["serving"], source_attempt=attempt,
    )
    archive, _ = deterministic_zip(package.path, root / "package.zip")
    stored = service.artifacts.ingest_file(archive)
    service.repository.bind_artifact_upload(artifact_id=stored["artifact_id"], node_id="worker", job=job, sha256=stored["sha256"])
    return {"package_id": package.package_id, "package_fingerprint": package.fingerprint,
            "formats": inputs["formats"], "artifacts": [{"kind": "export_package", **stored}]}


@pytest.mark.parametrize("kind", ["training.lora.v1", "training.distillation.v1", "model.export.v1"])
@pytest.mark.parametrize("fault", [None, "manifest", "metrics", "missing_artifact", "file", "duplicate", "missing_manifest"])
def test_ml_result_packages_and_reported_values_are_validated(tmp_path: Path, kind: str, fault: str | None) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    inputs = (training_inputs(distillation=kind == "training.distillation.v1") if kind != "model.export.v1" else {
        "source_training_manifest_sha256": "a" * 64, "source_artifact_reference": "sha256:" + "b" * 64,
        "formats": ["adapter"], "license_id": "apache-2.0", "serving": {"runtime": "transformers"},
        "collect_outputs": [{"result_key": "package_path", "kind": "export_package"}],
    })
    token, lease = started(service, kind=kind, inputs=inputs)
    result = (export_package(service, lease, tmp_path / "result") if kind == "model.export.v1"
              else training_package(service, lease, tmp_path / "result"))
    if fault == "manifest": result["package_fingerprint" if kind == "model.export.v1" else "manifest_sha256"] = "0" * 64
    elif fault == "metrics":
        if kind == "model.export.v1": result["formats"] = ["gguf"]
        else: result["metrics"] = {"train_loss": 999.0}
    elif fault == "missing_artifact": result["artifacts"] = []
    elif fault in {"file", "duplicate", "missing_manifest"}:
        descriptor = result["artifacts"][0]
        old = service.artifacts.blob_path(descriptor["sha256"])
        edited = tmp_path / "edited.zip"
        with zipfile.ZipFile(old) as source, zipfile.ZipFile(edited, "w") as target:
            names = source.namelist()
            manifest_name = next(name for name in names if name.endswith("manifest.json"))
            member = next(name for name in names if name != manifest_name)
            for name in names:
                if fault == "missing_manifest" and name == manifest_name: continue
                target.writestr(name, b"corrupt bytes" if fault == "file" and name == member else source.read(name))
            if fault == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate"):
                    target.writestr(manifest_name, source.read(manifest_name))
        stored = service.artifacts.ingest_file(edited)
        service.repository.bind_artifact_upload(artifact_id=stored["artifact_id"], node_id="worker",
                                                job=service.repository.job(lease["job_id"]), sha256=stored["sha256"])
        result["artifacts"] = [{"kind": descriptor["kind"], **stored}]
    if fault:
        with pytest.raises(ValueError): finish(service, token, lease, result)
        assert service.repository.job(lease["job_id"])["state"] == "acknowledged"
        assert service.repository.overview()["nodes"][0]["tested_workloads"] == []
    else:
        assert finish(service, token, lease, result)["accepted"] is True
        assert service.repository.job(lease["job_id"])["result_validation_version"] == 1
        assert service._verified_completed_ml_result(service.repository.job(lease["job_id"]))[0] == result


def test_legacy_ml_success_does_not_authorize_training_or_reappear_on_replay(tmp_path: Path) -> None:
    path = tmp_path / "coordinator.db"
    service = CoordinatorService(path)
    token, lease = started(service)
    result = preflight_package(service, lease, tmp_path / "result")
    response = finish(service, token, lease, result)
    original_token_hash = service.repository.node_record("worker")["auth_token_hash"]
    with service.repository.transaction() as db:
        db.execute("ALTER TABLE jobs DROP COLUMN result_validation_version")
    reopened = CoordinatorService(path)
    job = reopened.repository.job(lease["job_id"])
    assert job["state"] == "succeeded" and reopened.artifacts.verify(result["artifacts"][0]["sha256"])
    assert reopened.repository.node_record("worker")["auth_token_hash"] == original_token_hash
    assert reopened.repository.product_record(lease["job_id"])["status"] == "RESULT_REQUIRES_VALIDATION"
    assert reopened.repository.overview()["nodes"][0]["tested_workloads"] == []
    with pytest.raises(ValueError, match="new validated Worker execution"):
        reopened._verified_completed_ml_result(job)
    assert finish(reopened, token, lease, result) == response
    assert reopened.repository.overview()["nodes"][0]["tested_workloads"] == []
    assert reopened.repository.product_record(lease["job_id"])["status"] == "RESULT_REQUIRES_VALIDATION"


@pytest.mark.parametrize("kind", ["retrieval.benchmark.v1", "broker.agent_experiment.v1", "strategy.suite.v1"])
@pytest.mark.parametrize("fault", [None, "schema", "hash", "metrics", "review", "no_output_contract", "publication_interruption"])
def test_experiment_report_contracts_cannot_promote_discordant_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, fault: str | None) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    artifact_kind = {"retrieval.benchmark.v1": "retrieval_benchmark_report", "broker.agent_experiment.v1": "agent_experiment_report",
                     "strategy.suite.v1": "strategy_suite_report"}[kind]
    inputs = {"collect_outputs": [{"result_key": "report_dir", "kind": artifact_kind}]}
    if fault == "no_output_contract": inputs = {}
    token, lease = started(service, inputs=inputs, kind=kind)
    common = {"suite_fingerprint": "a" * 64, "snapshot_hash": "b" * 64, "case_ids": ["case-a"], "strategy_id": "R2"}
    model = {"provider": "local", "deployment": "test", "model": "model"}
    service.record_product_item(record_id=lease["job_id"], category="experiment", title="Protocol experiment",
                                status="EXPERIMENT_QUEUED", artifact_sha256="c" * 64, summary={**common, "target_model": model, "k": 5})
    report = {**common, "latency_ms": 10.0}
    result = {**common, "latency_ms": 10.0}
    if kind == "retrieval.benchmark.v1":
        name, schema = "retrieval-report.json", "retrieval-benchmark-report.v1"
        report.update({"strategy_id": "semantic.test.v1", "aggregate": {"recall_at_k": 1.0}})
        result.update({"strategy_contract": report["strategy_id"], "aggregate": report["aggregate"]})
    else:
        name, schema = ("agent-experiment.json", "broker-agent-experiment.v1") if kind == "broker.agent_experiment.v1" else ("strategy-report.json", "strategy-suite-report.v1")
        report.update({"target_model": model, "k": 5, "quality": {"deterministic_pass_rate": 1.0},
                       "results": [{"case_id": "case-a", "verification": {"deterministic_pass": True}}]})
        result["quality"] = report["quality"]
        if fault == "publication_interruption":
            candidates = [{"case_id": "case-a", "query": "Synthetic query", "snapshot_id": "snapshot-a", "prompt": "Synthetic prompt",
                           "retrieval_config": {}, "retrieved_context": [], "original_response": {"answer": "Synthetic response"},
                           "cost": {"amount": None, "currency": "USD", "source": "not_available", "verification_status": "unknown"}}]
            report["review_candidates"] = candidates
            result["review_candidates"] = candidates
    report["schema_version"] = "wrong.v1" if fault == "schema" else schema
    folder = tmp_path / "report"
    folder.mkdir()
    raw = (canonical_json(report) + "\n").encode("utf-8")
    (folder / name).write_bytes(raw)
    archive, _ = deterministic_zip(folder, tmp_path / "report.zip")
    stored = service.artifacts.ingest_file(archive)
    service.repository.bind_artifact_upload(artifact_id=stored["artifact_id"], node_id="worker",
                                            job=service.repository.job(lease["job_id"]), sha256=stored["sha256"])
    result.update({"report_sha256": "0" * 64 if fault == "hash" else hashlib.sha256(raw).hexdigest(),
                   "artifacts": [{"kind": artifact_kind, **stored}]})
    if fault == "metrics": result["aggregate" if kind == "retrieval.benchmark.v1" else "quality"] = {"invented_metric": 999}
    elif fault == "review":
        # Retrieval has no human-review candidates; its promoted latency is still bound.
        if kind == "retrieval.benchmark.v1": result["latency_ms"] = 999
        else: result["review_candidates"] = [{"case_id": "invented-review"}]
    if fault == "publication_interruption":
        publish = service.repository.record_product_item
        def interrupt_publication(**item):
            if item["status"] == "EXPERIMENT_SUCCEEDED": raise RuntimeError("simulated interruption after durable completion")
            return publish(**item)
        monkeypatch.setattr(service.repository, "record_product_item", interrupt_publication)
        with pytest.raises(RuntimeError, match="simulated interruption"): finish(service, token, lease, result)
        reopened = CoordinatorService(service.repository.path)
        assert finish(reopened, token, lease, result)["accepted"] is True
        assert finish(reopened, token, lease, result)["accepted"] is True
        assert reopened.repository.product_record(lease["job_id"])["status"] == "EXPERIMENT_SUCCEEDED"
        assert len(reopened.feedback.list_reviews()) == (0 if kind == "retrieval.benchmark.v1" else 1)
    elif fault:
        with pytest.raises(ValueError): finish(service, token, lease, result)
        assert service.repository.job(lease["job_id"])["state"] == "acknowledged"
        assert service.repository.overview()["nodes"][0]["tested_workloads"] == []
        assert service.repository.product_record(lease["job_id"])["status"] == "EXPERIMENT_QUEUED"
    else:
        assert finish(service, token, lease, result)["accepted"] is True
        assert finish(service, token, lease, result)["accepted"] is True
        assert service.repository.product_record(lease["job_id"])["status"] == "EXPERIMENT_SUCCEEDED"


def test_historical_export_remains_downloadable_after_contract_upgrade(tmp_path: Path) -> None:
    path = tmp_path / "coordinator.db"
    service = CoordinatorService(path)
    source = tmp_path / "old.zip"
    with zipfile.ZipFile(source, "w") as archive: archive.writestr("old.txt", "historical export")
    stored = service.artifacts.ingest_file(source)
    service.record_product_item(record_id="old-export", category="export", title="Old export", status="EXPORT_SUCCEEDED",
                                artifact_sha256=stored["sha256"], summary={})
    with service.repository.transaction() as db: db.execute("ALTER TABLE jobs DROP COLUMN result_validation_version")
    reopened = CoordinatorService(path)
    assert reopened.repository.product_record("old-export")["status"] == "RESULT_REQUIRES_VALIDATION"
    downloaded, media_type, filename = reopened.product_artifact("old-export")
    assert downloaded.read_bytes() == source.read_bytes() and media_type == "application/zip" and filename.endswith(".zip")
