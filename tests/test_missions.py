"""A mission resumes from persisted, current evidence rather than visited screens."""
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.jobs import JobSpec


def test_two_missions_reopen_and_status_tracks_evidence(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    service = CoordinatorService(database)
    first = service.save_mission(
        mission_id="mission-one", strategy="prompting", task="Responder sobre Atlas",
        success="Al menos 80 % de respuestas verificadas", constraints="sin cloud",
    )
    second = service.save_mission(
        mission_id="mission-two", strategy="distillation", task="Clasificar incidencias",
        success="Superar B0 en 0,05", constraints="licencias compatibles",
        teacher_source="broker", teacher_model="teacher-7b", student_model="student-1b",
    )
    assert first["stage_states"] == ["configured", "not_started", "not_started", "not_started", "not_started"]
    assert second["stage_states"][1] == "configured"
    assert first["resume_step"] == 1

    service.record_product_item(
        record_id="benchmark-one", category="benchmark", title="Atlas",
        status="HUMAN_APPROVED", artifact_sha256="a" * 64, summary={},
    )
    service.record_product_item(
        record_id="experiment-one", category="experiment", title="B0 Atlas",
        status="EXPERIMENT_QUEUED", artifact_sha256="b" * 64,
        summary={"benchmark_id": "benchmark-one", "suite_fingerprint": "a" * 64},
    )
    first = service.link_mission_evidence(
        mission_id="mission-one", stage_index=1,
        reference_kind="product", reference_id="benchmark-one",
    )
    first = service.link_mission_evidence(
        mission_id="mission-one", stage_index=2,
        reference_kind="product", reference_id="experiment-one",
    )
    assert first["stage_states"][1:3] == ["validated", "configured"]
    assert first["resume_step"] == 2
    with pytest.raises(ValueError, match="does not belong"):
        service.link_mission_evidence(
            mission_id="mission-two", stage_index=2,
            reference_kind="product", reference_id="experiment-one",
        )

    reopened = CoordinatorService(database)
    assert {item["mission_id"] for item in reopened.missions()} == {"mission-one", "mission-two"}
    assert reopened.mission("mission-one")["stage_states"][2] == "configured"
    reopened.record_product_item(
        record_id="experiment-one", category="experiment", title="B0 Atlas",
        status="EXPERIMENT_SUCCEEDED", artifact_sha256="b" * 64,
        summary={"benchmark_id": "benchmark-one", "suite_fingerprint": "a" * 64},
    )
    assert reopened.mission("mission-one")["stage_states"][2] == "executed"
    assert reopened.mission("mission-two")["stage_states"][2] == "not_started"
    job = JobSpec(kind="strategy.suite.v1", payload={"strategy_id": "B1"})
    reopened.submit_job(job, "mission-job")
    linked_job = reopened.link_mission_evidence(
        mission_id="mission-one", stage_index=2,
        reference_kind="job", reference_id=job.job_id,
    )
    assert any(link["reference_kind"] == "job" for link in linked_job["links"])
    with pytest.raises(ValueError, match="does not belong"):
        reopened.link_mission_evidence(
            mission_id="mission-two", stage_index=2,
            reference_kind="job", reference_id=job.job_id,
        )


def test_mission_routes_require_session_and_reject_wrong_stage(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    client = TestClient(create_app(service, app_token="session-test"))
    assert client.get("/app/v1/missions").status_code == 401
    headers = {"X-App-Token": "session-test"}
    payload = {
        "strategy": "rag", "task": "Responder con citas", "success": "80 % verificable",
        "constraints": "sin cloud", "teacher_source": None,
        "teacher_model": None, "student_model": None,
    }
    response = client.put("/app/v1/missions/rag-one", headers=headers, json=payload)
    assert response.status_code == 200
    assert response.json()["resume_step"] == 1
    assert len(client.get("/app/v1/missions", headers=headers).json()) == 1
    service.record_product_item(
        record_id="rag-benchmark", category="benchmark", title="Preguntas RAG",
        status="HUMAN_APPROVED", artifact_sha256="e" * 64, summary={},
    )
    linked = client.post(
        "/app/v1/missions/rag-one/links", headers=headers,
        json={"stage_index": 2, "reference_kind": "product", "reference_id": "rag-benchmark"},
    )
    assert linked.status_code == 200
    assert linked.json()["stage_states"][2] == "configured"
    assert "snapshot" in linked.json()["links"][0]["reason"]
    unlinked = client.post(
        "/app/v1/missions/rag-one/unlink", headers=headers,
        json={"stage_index": 2, "reference_kind": "product", "reference_id": "rag-benchmark"},
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["stage_states"][2] == "not_started"
    response = client.post(
        "/app/v1/missions/rag-one/links", headers=headers,
        json={"stage_index": 5, "reference_kind": "product", "reference_id": "unknown"},
    )
    assert response.status_code == 422


def test_rag_stage_needs_matching_snapshot_and_index(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "state.db")
    service.save_mission(
        mission_id="rag-plan", strategy="rag", task="Responder sobre Atlas",
        success="Citas verificables en 8 de 10 casos",
    )
    service.record_product_item(
        record_id="snapshot-atlas", category="snapshot", title="Vault Atlas",
        status="COMPLETE", artifact_sha256="a" * 64, summary={},
    )
    service.record_product_item(
        record_id="index-wrong", category="index", title="Índice ajeno",
        status="READY", artifact_sha256="b" * 64,
        summary={"snapshot_id": "another", "snapshot_hash": "c" * 64},
    )
    service.record_product_item(
        record_id="index-atlas", category="index", title="Índice Atlas",
        status="READY", artifact_sha256="d" * 64,
        summary={"snapshot_id": "snapshot-atlas", "snapshot_hash": "a" * 64},
    )
    plan = service.link_mission_evidence(
        mission_id="rag-plan", stage_index=1,
        reference_kind="product", reference_id="snapshot-atlas",
    )
    with pytest.raises(ValueError, match="procedencia"):
        service.link_mission_evidence(
            mission_id="rag-plan", stage_index=1,
            reference_kind="product", reference_id="index-wrong",
        )
    assert plan["stage_states"][1] == "configured"
    plan = service.link_mission_evidence(
        mission_id="rag-plan", stage_index=1,
        reference_kind="product", reference_id="index-atlas",
    )
    assert plan["stage_states"][1] == "validated"


def _product(service, record_id, category, status, summary=None, digest="a" * 64):
    service.record_product_item(record_id=record_id, category=category, title=record_id,
                                status=status, artifact_sha256=digest, summary=summary or {})


def _link(service, mission_id, stage, record_id, kind="product"):
    return service.link_mission_evidence(mission_id=mission_id, stage_index=stage,
                                         reference_kind=kind, reference_id=record_id)


def test_foreign_runs_reviews_and_comparisons_do_not_complete_a_mission(tmp_path: Path):
    service = CoordinatorService(tmp_path / "state.db")
    service.save_mission(mission_id="one", strategy="prompting", task="Atlas", success="8 de 10")
    _product(service, "suite-one", "benchmark", "HUMAN_APPROVED")
    _link(service, "one", 1, "suite-one")
    _product(service, "run-foreign", "experiment", "EXPERIMENT_SUCCEEDED",
             {"benchmark_id": "suite-two", "suite_fingerprint": "b" * 64})
    with pytest.raises(ValueError, match="procedencia"):
        _link(service, "one", 2, "run-foreign")
    _product(service, "run-one", "experiment", "EXPERIMENT_SUCCEEDED",
             {"benchmark_id": "suite-one", "suite_fingerprint": "a" * 64, "case_ids": ["case-one"]})
    _link(service, "one", 2, "run-one")
    context = {
        "query": "Atlas", "strategy_id": "B1", "model": "local", "prompt": "Pregunta",
        "retrieval_config": {}, "snapshot_id": "snapshot-one", "retrieved_context": [],
        "estimated_tokens": None, "cost": {"amount": None, "currency": "USD",
                                            "source": "not_available", "verification_status": "unknown"},
    }
    foreign = service.feedback.create_review(
        run_id="run-foreign", case_id="case-one", snapshot_id="snapshot-one", reviewer="person",
        run_context=context, original_response={"answer": "Respuesta"},
    )
    with pytest.raises(ValueError, match="procedencia"):
        _link(service, "one", 3, foreign["review_id"], "review")
    own = service.feedback.create_review(
        run_id="run-one", case_id="case-one", snapshot_id="snapshot-one", reviewer="person",
        run_context=context, original_response={"answer": "Respuesta"},
    )
    _link(service, "one", 3, own["review_id"], "review")
    _product(service, "choice", "comparison", "RECOMMENDATION",
             {"experiment_ids": ["run-one", "run-foreign"]})
    plan = _link(service, "one", 4, "choice")
    assert plan["stage_states"][4] == "configured"
    assert "todos los experimentos" in plan["links"][-1]["reason"]
    _product(service, "run-two", "experiment", "EXPERIMENT_SUCCEEDED",
             {"benchmark_id": "suite-one", "suite_fingerprint": "a" * 64})
    _link(service, "one", 2, "run-two")
    _product(service, "choice", "comparison", "RECOMMENDATION",
             {"experiment_ids": ["run-one", "run-two"]})
    assert service.mission("one")["stage_states"][4] == "validated"
    service.unlink_mission_evidence(mission_id="one", stage_index=1,
                                   reference_kind="product", reference_id="suite-one")
    reopened = CoordinatorService(tmp_path / "state.db").mission("one")
    assert reopened["stage_states"][2:] == ["configured", "configured", "configured"]


def test_training_mission_preserves_dataset_preflight_evaluation_and_export_lineage(tmp_path: Path):
    service = CoordinatorService(tmp_path / "state.db")
    service.save_mission(mission_id="train", strategy="lora", task="Clasificar", success="Mejorar 0,05")
    _product(service, "data", "dataset", "READY_FOR_TRAINING")
    _link(service, "train", 1, "data")
    _product(service, "preflight", "training", "PREFLIGHT_PASSED",
             {"kind": "training.preflight.v1", "dataset_id": "data"})
    _link(service, "train", 2, "preflight")
    details = {"kind": "training.lora.v1", "dataset_id": "data",
               "preflight_job_id": "preflight", "baseline_experiment_id": "baseline"}
    _product(service, "trained", "training", "TRAINING_SUCCEEDED", details)
    _link(service, "train", 3, "trained")
    _product(service, "foreign-preflight", "training", "PREFLIGHT_PASSED",
             {"kind": "training.preflight.v1", "dataset_id": "other-data"})
    with pytest.raises(ValueError, match="procedencia"):
        _link(service, "train", 2, "foreign-preflight")
    _product(service, "bad-hash", "training", "PREFLIGHT_PASSED",
             {"kind": "training.preflight.v1", "dataset_id": "data", "dataset_fingerprint": "b" * 64})
    with pytest.raises(ValueError, match="procedencia"):
        _link(service, "train", 2, "bad-hash")
    _product(service, "foreign-evaluation", "experiment", "EXPERIMENT_SUCCEEDED",
             {"training_job_id": "other-trained"})
    with pytest.raises(ValueError, match="procedencia"):
        _link(service, "train", 4, "foreign-evaluation")
    _product(service, "baseline", "experiment", "EXPERIMENT_SUCCEEDED")
    _product(service, "evaluation", "experiment", "EXPERIMENT_SUCCEEDED", {"training_job_id": "trained"})
    for run in ("baseline", "evaluation"):
        _link(service, "train", 4, run)
    assert service.mission("train")["stage_states"][4] == "configured"
    assert service.mission("train")["resume_step"] == 4
    _product(service, "comparison", "comparison", "RECOMMENDATION",
             {"experiment_ids": ["baseline", "evaluation"]})
    _link(service, "train", 4, "comparison")
    _product(service, "foreign-export", "export", "EXPORT_SUCCEEDED", {"training_job_id": "other-trained"})
    with pytest.raises(ValueError, match="procedencia"):
        _link(service, "train", 5, "foreign-export")
    _product(service, "export", "export", "EXPORT_SUCCEEDED", {"training_job_id": "trained"})
    plan = _link(service, "train", 5, "export")
    assert plan["stage_states"] == ["configured", "validated", "validated", "executed", "validated", "validated"]
    _product(service, "trained", "training", "FAILED", details)
    plan = service.mission("train")
    assert plan["stage_states"][3:] == ["attention", "configured", "configured"]
    assert plan["resume_step"] == 3


def test_distillation_plan_model_changes_invalidate_previous_evidence(tmp_path: Path):
    service = CoordinatorService(tmp_path / "state.db")
    fields = dict(mission_id="distill", strategy="distillation", task="Clasificar", success="Mejorar 0,05",
                  teacher_source="local", teacher_model="teacher", student_model="student")
    service.save_mission(**fields)
    _product(service, "data", "dataset", "READY_FOR_TRAINING")
    _link(service, "distill", 2, "data")
    _product(service, "preflight", "training", "PREFLIGHT_PASSED",
             {"kind": "training.preflight.v1", "dataset_id": "data", "base_model": "student"})
    _link(service, "distill", 3, "preflight")
    _product(service, "trained", "training", "DISTILLATION_SUCCEEDED",
             {"kind": "training.distillation.v1", "dataset_id": "data", "preflight_job_id": "preflight",
              "teacher_model": "teacher", "teacher_source": "local", "student_model": "student"})
    _link(service, "distill", 4, "trained")
    changed = service.save_mission(**{**fields, "student_model": "another-student"})
    assert changed["stage_states"][3:5] == ["attention", "attention"]
    assert all("alumno" in link["reason"] for link in changed["links"] if link["category"] == "training")


def test_missing_mission_evidence_remains_readable(tmp_path: Path):
    service = CoordinatorService(tmp_path / "state.db")
    service.save_mission(mission_id="one", strategy="rag", task="Atlas", success="8 de 10")
    _product(service, "snapshot", "snapshot", "COMPLETE")
    _link(service, "one", 1, "snapshot")
    with service.repository.transaction() as connection:
        connection.execute("DELETE FROM product_records WHERE record_id='snapshot'")
    client = TestClient(create_app(service, app_token="session-test"))
    result = client.get("/app/v1/missions", headers={"X-App-Token": "session-test"})
    assert result.status_code == 200
    missing = result.json()[0]["links"][0]
    assert missing["category"] == "unknown"
    assert missing["stage_state"] == "attention"
    assert result.json()[0]["stage_states"][1] == "attention"
