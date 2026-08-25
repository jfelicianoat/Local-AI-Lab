from __future__ import annotations

import json
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.domain.jobs import JobSpec, JobState


def test_controlled_r1_benchmark_runs_and_is_persisted_as_product_evidence(
    tmp_path: Path,
) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    record = service.run_controlled_retrieval_benchmark(k=5)

    assert record["category"] == "experiment"
    assert record["status"] == "PENDING_HUMAN_REVIEW"
    assert record["summary"]["strategy_id"] == "R1.lexical-fts5.v1"
    assert 0 <= record["summary"]["recall_at_k"] <= 1
    artifact = service.repository.artifact_location(
        record["record_id"], expected_kind="retrieval_benchmark_report"
    )
    assert artifact.is_file()
    assert service.product_workspace()["experiments"][0]["record_id"] == record["record_id"]


def test_controlled_benchmark_desktop_route_requires_session_and_returns_record(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(CoordinatorService(tmp_path / "coordinator.db"), app_token="desktop-token")
    )
    assert client.post("/app/v1/benchmarks/controlled/retrieval", json={"k": 3}).status_code == 401

    response = client.post(
        "/app/v1/benchmarks/controlled/retrieval",
        headers={"X-App-Token": "desktop-token"},
        json={"k": 3},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["k"] == 3


def test_dataset_workflow_consumes_only_explicitly_approved_feedback(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Atlas.md").write_text("# Owner\nAna Torres dirige Atlas.", encoding="utf-8")
    snapshot_record = service.create_vault_snapshot(allowed_root=allowed, vault_name="Test")
    snapshot_path = service.repository.artifact_location(
        snapshot_record["record_id"], expected_kind="vault_snapshot"
    )
    note = json.loads((snapshot_path / "notes.jsonl").read_text(encoding="utf-8"))
    chunk = json.loads((snapshot_path / "chunks.jsonl").read_text(encoding="utf-8"))
    evidence = {
        "snapshot_id": snapshot_record["record_id"], "note_id": note["note_id"],
        "note_path": note["relative_path"], "section": chunk["section"],
        "chunk_id": chunk["chunk_id"],
        "source_reference": f"snapshot:sha256:{snapshot_record['artifact_sha256']}#chunk:{chunk['chunk_id']}",
    }
    response = {
        "answer": "Ana Torres dirige Atlas.",
        "findings": [{"claim": "Ana Torres dirige Atlas.", "evidence": [evidence]}],
        "contradictions": [], "uncertainties": [], "missing_information": [],
    }
    context = {
        "query": "¿Quién dirige Atlas?", "strategy_id": "R3.hybrid-rrf.v1",
        "model": "local/test-model", "prompt": "Responde con evidencia.",
        "retrieval_config": {"k": 5}, "snapshot_id": snapshot_record["record_id"],
        "retrieved_context": [evidence], "estimated_tokens": 24,
        "cost": {"amount": None, "currency": "USD", "source": "not_available", "verification_status": "unknown"},
    }
    review = service.feedback.create_review(
        run_id="run-real-1", case_id="private-case-1", snapshot_id=snapshot_record["record_id"],
        reviewer="human-reviewer", run_context=context, original_response=response,
    )
    service.save_review_correction(
        review_id=review["review_id"], actor="human-reviewer", corrected_response=response
    )
    service.transition_review(review_id=review["review_id"], to_state="submitted", actor="human-reviewer")
    service.transition_review(review_id=review["review_id"], to_state="accepted", actor="lead-reviewer")
    service.transition_training_candidate(
        review_id=review["review_id"], to_state="proposed", actor="human-reviewer"
    )
    service.transition_training_candidate(
        review_id=review["review_id"], to_state="approved", actor="lead-reviewer"
    )

    record = service.build_approved_feedback_dataset(
        name="private-feedback-v1", split_seed="controlled-seed-2026", actor="dataset-builder"
    )

    assert record["category"] == "dataset"
    assert record["summary"]["included"] == 1
    assert service.feedback.get(review["review_id"])["training_state"] == "exported"

    pairing = service.create_pairing_code()
    registration = service.pair_and_register(
        pairing_code=pairing, node_id="worker-nvidia", hostname="nvidia-host"
    )
    token = registration["device_token"]
    preflight = service.create_training_preflight_job(
        dataset_id=record["record_id"], node_id="worker-nvidia",
        base_model="local/model-cache", dtype="bf16", seed=42, max_length=2048,
        lora_config={"rank": 8, "alpha": 16}, idempotency_key="preflight-submit",
    )
    preflight_job = service.repository.job(preflight["record_id"])
    preflight_payload = json.loads(preflight_job["spec_json"])["payload"]
    assert "resolved_dataset_path" not in preflight_payload
    assert preflight_payload["input_artifacts"][0]["sha256"] == record["summary"]["cas_sha256"]

    lease = service.claim_job(
        node_id="worker-nvidia", token=token, idempotency_key="claim-preflight"
    )
    service.ack_job(
        node_id="worker-nvidia", token=token, job_id=lease["job_id"],
        lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
        idempotency_key="ack-preflight",
    )
    contract = {
        "c1_assistant_only_loss": True, "c2_supervised_eos": True,
        "c3_same_chat_template": True, "c4_assistant_not_truncated": True,
        "c5_padding_outside_loss": True, "c6_seed_and_nondeterminism_recorded": True,
        "errors": [], "passed": True,
    }
    checks = {
        "overfit_8_examples": True, "save": True, "reload": True, "resume": True,
        "contamination_check": True, "manifest_check": True,
    }
    service.complete_job(
        node_id="worker-nvidia", token=token, job_id=lease["job_id"],
        attempt_id=lease["attempt_id"], lease_token=lease["lease_token"],
        lease_generation=lease["lease_generation"], outcome="succeeded",
        payload={
            "preflight_sha256": "1" * 64, "dataset_fingerprint": record["artifact_sha256"],
            "chat_template_fingerprint": "2" * 64, "dtype": "bf16", "backend": "cuda",
            "contract": contract, "checks": checks,
        },
        idempotency_key="complete-preflight",
    )
    baseline = service.run_controlled_retrieval_benchmark(k=5)
    training = service.create_training_job(
        dataset_id=record["record_id"], preflight_job_id=preflight["record_id"],
        baseline_experiment_id=baseline["record_id"], objective="format",
        hypothesis="El adapter reducirá errores de esquema sin memorizar hechos.",
        approved_by="lead-reviewer", epochs=1.0, idempotency_key="training-submit",
    )
    training_spec = json.loads(service.repository.job(training["record_id"])["spec_json"])
    assert training["status"] == "TRAINING_QUEUED"
    assert training_spec["payload"]["input_artifacts"][0]["sha256"] == record["summary"]["cas_sha256"]

    distillation = service.create_distillation_job(
        dataset_id=record["record_id"],
        preflight_job_id=preflight["record_id"],
        baseline_experiment_id=baseline["record_id"],
        teacher_model="local/teacher-cache",
        teacher_model_fingerprint="3" * 64,
        student_model="local/model-cache",
        student_model_fingerprint="4" * 64,
        teacher_license="Apache-2.0",
        student_license="Apache-2.0",
        teacher_outputs_training_allowed=True,
        student_finetuning_allowed=True,
        objective="behavior",
        hypothesis="El alumno conservará la calidad del profesor con menor coste.",
        approved_by="lead-reviewer",
        epochs=1.0,
        generation_config={"temperature": 0.0, "max_new_tokens": 256},
        idempotency_key="distillation-submit",
    )
    distillation_spec = json.loads(
        service.repository.job(distillation["record_id"])["spec_json"]
    )
    assert distillation["status"] == "DISTILLATION_QUEUED"
    assert distillation_spec["kind"] == "training.distillation.v1"
    assert distillation_spec["payload"]["teacher_model"] == "local/teacher-cache"
    assert distillation_spec["payload"]["student_model"] == "local/model-cache"
    assert distillation_spec["payload"]["input_artifacts"][0]["sha256"] == record["summary"]["cas_sha256"]
    assert distillation_spec["requirements"]["required_workloads"] == ["training.lora"]

    service.record_product_item(
        record_id="broker-distillation",
        category="experiment",
        title="AI Broker · modelo exacto",
        status="CAPABILITIES_SATISFIED",
        artifact_sha256="6" * 64,
        summary={
            "phase": "retrieval",
            "endpoint": "http://127.0.0.1:8000",
            "observed_contract": "2.9",
        },
    )
    broker_distillation = service.create_distillation_job(
        dataset_id=record["record_id"],
        preflight_job_id=preflight["record_id"],
        baseline_experiment_id=baseline["record_id"],
        teacher_source="broker",
        broker_check_id="broker-distillation",
        teacher_broker_endpoint="http://127.0.0.1:8000",
        teacher_target_model={
            "provider": "local",
            "deployment": "qwen-teacher",
            "model": "qwen-teacher",
        },
        teacher_model="qwen-teacher",
        teacher_model_fingerprint=None,
        student_model="local/model-cache",
        student_model_fingerprint="4" * 64,
        teacher_license="Términos del deployment revisados",
        student_license="Apache-2.0",
        teacher_outputs_training_allowed=True,
        student_finetuning_allowed=True,
        objective="behavior",
        hypothesis="El profesor del Broker mejorará al alumno local.",
        approved_by="lead-reviewer",
        epochs=1.0,
        generation_config={"temperature": 0.0, "max_new_tokens": 256},
        idempotency_key="broker-distillation-submit",
    )
    broker_spec = json.loads(
        service.repository.job(broker_distillation["record_id"])["spec_json"]
    )
    assert broker_spec["payload"]["teacher_source"] == "broker"
    assert broker_spec["payload"]["teacher_target_model"]["model"] == "qwen-teacher"
    assert len(broker_spec["payload"]["teacher_model_fingerprint"]) == 64
    assert "token" not in broker_spec["payload"]
    assert "broker_token" not in broker_spec["payload"]

    client = TestClient(create_app(service, app_token="desktop-token"))
    response = client.post(
        "/app/v1/training/distillation",
        headers={"X-App-Token": "desktop-token"},
        json={
            "dataset_id": record["record_id"],
            "preflight_job_id": preflight["record_id"],
            "baseline_experiment_id": baseline["record_id"],
            "teacher_model": "local/teacher-cache-v2",
            "teacher_model_fingerprint": "5" * 64,
            "student_model": "local/model-cache",
            "student_model_fingerprint": "4" * 64,
            "teacher_license": "Apache-2.0",
            "student_license": "Apache-2.0",
            "teacher_outputs_training_allowed": True,
            "student_finetuning_allowed": True,
            "objective": "behavior",
            "hypothesis": "La segunda pareja también debe superar el baseline.",
            "approved_by": "lead-reviewer",
            "epochs": 1.0,
            "generation_config": {"temperature": 0.2, "max_new_tokens": 128},
            "idempotency_key": "distillation-api-submit",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DISTILLATION_QUEUED"


def test_export_job_uses_portable_training_artifact_and_tested_worker_capability(
    tmp_path: Path,
) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite3")
    code = service.create_pairing_code()
    registration = service.pair_and_register(
        pairing_code=code, node_id="worker-export", hostname="worker-export"
    )
    service.heartbeat(
        node_id="worker-export",
        token=registration["device_token"],
        capabilities={
            "facts": [],
            "workloads": [{"kind": "export.adapter", "status": "tested"}],
        },
    )
    training_root = tmp_path / "training-output"
    (training_root / "adapter").mkdir(parents=True)
    (training_root / "adapter" / "adapter.safetensors").write_bytes(b"adapter")
    manifest_path = training_root / "training-manifest.json"
    manifest_path.write_text('{"content_sha256":"' + "a" * 64 + '"}\n', encoding="utf-8")
    archive_path, _ = deterministic_zip(training_root, tmp_path / "training.zip")
    stored = service.artifacts.ingest_file(archive_path)
    training = JobSpec(kind="training.lora.v1", payload={"base_model": "local/model"})
    service.submit_job(training, "training-result-fixture")
    result = {
        "manifest_sha256": "a" * 64,
        "manifest_file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "artifacts": [{
            "kind": "training_result", "sha256": stored["sha256"], "size": stored["size"]
        }],
    }
    with service.repository.transaction() as db:
        db.execute(
            "UPDATE jobs SET state=?, result_json=? WHERE job_id=?",
            (JobState.SUCCEEDED, canonical_json(result), training.job_id),
        )
    service.record_product_item(
        record_id=training.job_id, category="training", title="Training fixture",
        status="TRAINING_SUCCEEDED", artifact_sha256=stored["sha256"],
        summary={"job_id": training.job_id},
    )

    created = service.create_export_job(
        training_job_id=training.job_id, node_id="worker-export", formats=["adapter"],
        license_id="apache-2.0", serving={"runtime": "transformers", "local_only": True},
        llama_cpp_converter=None, idempotency_key="export-fixture",
    )
    queued = service.repository.job(created["record_id"])
    assert queued is not None
    spec = json.loads(queued["spec_json"])
    assert spec["payload"]["input_artifacts"] == [{
        "archive": "zip", "mount_as": "resolved_training_output", "sha256": stored["sha256"]
    }]
    assert "resolved_training_output" not in spec["payload"]
    assert spec["requirements"]["required_workloads"] == ["export.adapter"]


def test_strategy_and_agent_jobs_use_capability_evidence_without_persisting_broker_token(
    tmp_path: Path,
) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite3")
    code = service.create_pairing_code()
    registration = service.pair_and_register(
        pairing_code=code, node_id="worker-lab", hostname="worker-lab"
    )
    service.heartbeat(
        node_id="worker-lab", token=registration["device_token"],
        capabilities={
            "facts": [
                {"key": "broker.contract_version", "value": "2.9"},
                {"key": "broker.strategy.agent", "value": True},
            ],
            "workloads": [
                {"kind": "broker.single_experiment", "status": "tested"},
                {"kind": "broker.agent_experiment", "status": "tested"},
                {"kind": "embeddings.semantic", "status": "tested"},
            ],
        },
    )
    for record_id, phase in (("broker-retrieval", "retrieval"), ("broker-agents", "agent_experiments")):
        service.record_product_item(
            record_id=record_id, category="experiment", title="Broker check",
            status="CAPABILITIES_SATISFIED", artifact_sha256=("b" if phase == "retrieval" else "c") * 64,
            summary={"phase": phase, "observed_contract": "2.9"},
        )
    target = {"provider": "local", "deployment": "desktop", "model": "exact-model"}
    baseline = service.create_strategy_suite_job(
        strategy_id="B0", broker_check_id="broker-retrieval",
        broker_endpoint="http://127.0.0.1:8765", node_id="worker-lab",
        target_model=target, embedding_model=None, embedding_model_fingerprint=None,
        device="cpu", training_job_id=None, k=5, idempotency_key="strategy-b0",
    )
    agent = service.create_broker_agent_experiment_job(
        strategy_id="A1", broker_check_id="broker-agents",
        broker_endpoint="http://127.0.0.1:8765", node_id="worker-lab",
        target_model=target, embedding_model="local/embeddings",
        embedding_model_fingerprint="d" * 64, device="cpu", k=5,
        idempotency_key="agent-a1",
    )
    for record in (baseline, agent):
        job = service.repository.job(record["record_id"])
        assert job is not None
        encoded = job["spec_json"]
        assert "token" not in encoded.casefold()
        spec = json.loads(encoded)
        assert all("sha256" in item and "mount_as" in item for item in spec["payload"]["input_artifacts"])
        assert "resolved_snapshot" not in spec["payload"]
