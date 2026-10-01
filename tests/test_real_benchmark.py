from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from local_ai_lab.benchmark.real import RealBenchmarkSuite, RealBenchmarkValidationError
from local_ai_lab.coordinator.service import CoordinatorService


def _definition() -> dict:
    return {
        "schema_version": "real-benchmark.v1", "suite_id": "real-research-v1",
        "version": "1.0.0", "purpose": "external_validity", "training_eligible": False,
        "snapshot_hash": "a" * 64,
        "human_review": {
            "status": "approved", "reviewer_kind": "human", "reviewer": "Ana",
            "reviewed_at": "2026-08-23T00:00:00Z",
        },
        "cases": [{
            "case_id": "project-evolution", "query": "¿Cómo evolucionó el proyecto?",
            "reference_answer": {
                "author_kind": "human", "author": "Ana", "answer": "Respuesta humana.",
                "evidence": [{
                    "note_id": "note-1", "note_path": "Project.md", "section": "Decision",
                    "chunk_id": "b" * 64,
                    "source_reference": "snapshot:sha256:" + "a" * 64 + "#chunk:" + "b" * 64,
                }],
            },
        }],
    }


def test_real_benchmark_requires_human_reference_and_is_not_training_data(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(_definition()), encoding="utf-8")
    suite = RealBenchmarkSuite.load(path)

    assert suite.definition["training_eligible"] is False
    assert suite.definition["human_review"]["reviewer_kind"] == "human"
    assert len(suite.fingerprint) == 64


def test_real_benchmark_rejects_model_authored_ground_truth(tmp_path: Path) -> None:
    definition = _definition()
    definition["cases"][0]["reference_answer"]["author_kind"] = "model"
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(definition), encoding="utf-8")

    with pytest.raises(RealBenchmarkValidationError, match="human-authored"):
        RealBenchmarkSuite.load(path)


def test_real_benchmark_pending_review_cannot_close_gate(tmp_path: Path) -> None:
    definition = _definition()
    definition["human_review"]["status"] = "pending"
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(definition), encoding="utf-8")

    with pytest.raises(RealBenchmarkValidationError, match="pending human approval"):
        RealBenchmarkSuite.load(path)


def test_registered_real_benchmark_rejects_invented_snapshot_citation(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Project.md").write_text("# Decision\nRespuesta humana.", encoding="utf-8")
    snapshot = service.create_vault_snapshot(allowed_root=allowed, vault_name="Test")
    definition = _definition()
    definition["snapshot_hash"] = snapshot["artifact_sha256"]
    definition["cases"][0]["reference_answer"]["evidence"][0]["source_reference"] = (
        f"snapshot:sha256:{snapshot['artifact_sha256']}#chunk:{'b' * 64}"
    )
    with pytest.raises(RealBenchmarkValidationError, match="absent from the snapshot"):
        service.register_real_benchmark(definition=definition)


def test_real_snapshot_suite_and_index_reach_experiment_job(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Project.md").write_text("# Decision\nAna Torres dirige Atlas.", encoding="utf-8")
    snapshot = service.create_vault_snapshot(allowed_root=allowed, vault_name="Test")
    index = service.create_knowledge_index(snapshot_id=snapshot["record_id"])
    source = service.repository.artifact_location(snapshot["record_id"], expected_kind="vault_snapshot")
    note = json.loads((source / "notes.jsonl").read_text(encoding="utf-8"))
    chunk = json.loads((source / "chunks.jsonl").read_text(encoding="utf-8"))
    definition = _definition()
    definition["snapshot_hash"] = snapshot["artifact_sha256"]
    case = definition["cases"][0]
    case["case_id"] = "vault-case-unique"
    case["query"] = "¿Quién dirige Atlas?"
    case["reference_answer"]["answer"] = "Ana Torres."
    case["reference_answer"]["evidence"] = [{
        "note_id": note["note_id"], "note_path": note["relative_path"],
        "section": chunk["section"], "chunk_id": chunk["chunk_id"],
        "source_reference": f"snapshot:sha256:{snapshot['artifact_sha256']}#chunk:{chunk['chunk_id']}",
    }]
    benchmark = service.register_real_benchmark(definition=definition)
    selected = dict(
        benchmark_id=benchmark["record_id"], snapshot_id=snapshot["record_id"],
        index_id=index["record_id"],
    )
    lexical = service.run_controlled_retrieval_benchmark(k=1, **selected)
    assert lexical["status"] == "LOCAL_VERIFIED"
    assert lexical["summary"]["case_ids"] == ["vault-case-unique"]
    assert lexical["summary"]["snapshot_hash"] == snapshot["artifact_sha256"]

    code = service.create_pairing_code()
    service.pair_and_register(pairing_code=code, node_id="worker", hostname="worker")
    service.record_product_item(
        record_id="broker-check", category="experiment", title="Broker check",
        status="CAPABILITIES_SATISFIED", artifact_sha256="c" * 64,
        summary={"phase": "retrieval", "endpoint": "http://127.0.0.1:8765"},
    )
    job_record = service.create_strategy_suite_job(
        strategy_id="B1", broker_check_id="broker-check",
        broker_endpoint="http://127.0.0.1:8765", node_id="worker",
        target_model={"provider": "local", "deployment": "test", "model": "model"},
        embedding_model=None, embedding_model_fingerprint=None, device="cpu",
        training_job_id=None, k=1, idempotency_key="real-job", **selected,
    )
    spec = json.loads(service.repository.job(job_record["record_id"])["spec_json"])
    assert job_record["summary"]["case_ids"] == ["vault-case-unique"]
    suite_sha = next(item["sha256"] for item in spec["payload"]["input_artifacts"] if item["mount_as"] == "resolved_suite")
    with zipfile.ZipFile(service.artifacts.blob_path(suite_sha)) as archive:
        packaged = json.loads(archive.read("real-benchmark.json"))
    assert packaged["cases"][0]["query"] == "¿Quién dirige Atlas?"


def test_manual_training_query_is_separate_from_benchmark_and_builds_dataset(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Project.md").write_text("# Decision\nAna Torres dirige Atlas.", encoding="utf-8")
    snapshot = service.create_vault_snapshot(allowed_root=allowed, vault_name="Test")
    index = service.create_knowledge_index(snapshot_id=snapshot["record_id"])
    source = service.repository.artifact_location(snapshot["record_id"], expected_kind="vault_snapshot")
    note = json.loads((source / "notes.jsonl").read_text(encoding="utf-8"))
    chunk = json.loads((source / "chunks.jsonl").read_text(encoding="utf-8"))
    definition = _definition()
    definition["snapshot_hash"] = snapshot["artifact_sha256"]
    definition["cases"][0]["query"] = "¿Quién dirige Atlas?"
    definition["cases"][0]["reference_answer"]["evidence"] = [{
        "note_id": note["note_id"], "note_path": note["relative_path"],
        "section": chunk["section"], "chunk_id": chunk["chunk_id"],
        "source_reference": f"snapshot:sha256:{snapshot['artifact_sha256']}#chunk:{chunk['chunk_id']}",
    }]
    service.register_real_benchmark(definition=definition)
    kwargs = {"snapshot_id": snapshot["record_id"], "index_id": index["record_id"]}
    with pytest.raises(ValueError, match="duplicates an approved benchmark"):
        service.create_manual_example_review(
            **kwargs, query="¿Quién dirige Atlas?", answer="Ana Torres dirige Atlas.",
            chunk_ids=[chunk["chunk_id"]], reviewer="Ana",
        )
    hits = service.preview_manual_example(**kwargs, query="¿Quién lidera Atlas?")
    assert hits[0]["chunk_id"] == chunk["chunk_id"]
    review = service.create_manual_example_review(
        **kwargs, query="¿Quién lidera Atlas?", answer="Ana Torres dirige Atlas.",
        chunk_ids=[hits[0]["chunk_id"]], reviewer="Ana",
    )
    assert review["status"] == "draft"
    assert "Ana Torres dirige Atlas." in review["context"]["retrieved_context"][0]["content"]
    corrected = service.save_review_correction(
        review_id=review["review_id"], actor="Ana", corrected_response=review["original"],
    )
    assert corrected["verification"]["deterministic_pass"] is True
    service.transition_review(review_id=review["review_id"], to_state="submitted", actor="Ana")
    service.transition_review(review_id=review["review_id"], to_state="accepted", actor="Ana")
    service.transition_training_candidate(review_id=review["review_id"], to_state="proposed", actor="Ana")
    service.transition_training_candidate(review_id=review["review_id"], to_state="approved", actor="Ana")
    dataset = service.build_approved_feedback_dataset(name="manual-examples", split_seed="private-seed-2026", actor="Ana")
    assert dataset["summary"]["included"] == 1
