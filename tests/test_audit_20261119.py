"""Regression workflows: concurrent editing, restoration and approval revocation."""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.api.modelos import MissionSaveRequest
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.dataset.factory import DatasetFactory
from local_ai_lab.feedback.repository import FeedbackConflictError
from local_ai_lab.maintenance.backup import create_backup, restore_backup
from test_dataset_factory import _approved


def test_mission_stale_writer_cannot_overwrite_saved_work(tmp_path):
    database = tmp_path / "state.db"
    app = create_app(CoordinatorService(database), app_token="audit")
    route = next(route.endpoint for route in app.routes if route.path == "/app/v1/missions/{mission_id}")
    def put(body):
        return route(mission_id="m1", body=MissionSaveRequest(**body), x_app_token="audit")
    body = {"strategy": "prompting", "task": "Primera tarea", "success": "80 %"}
    assert put(body)["revision"] == 1
    second = {**body, "task": "Trabajo nuevo", "expected_revision": 1}
    assert put(second)["revision"] == 2
    with pytest.raises(HTTPException) as stale:
        put({**body, "expected_revision": 1})
    assert stale.value.status_code == 409
    # Older clients omitting the revision must also fail to overwrite existing work.
    with pytest.raises(HTTPException) as legacy:
        put(body)
    assert legacy.value.status_code == 409
    reopened = CoordinatorService(database).mission("m1")
    assert reopened["task"] == "Trabajo nuevo" and reopened["revision"] == 2


def test_mission_migration_preserves_content_and_links(tmp_path):
    database = tmp_path / "old.db"
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE mission_plans (
            mission_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, task TEXT NOT NULL,
            success TEXT NOT NULL, constraints_text TEXT NOT NULL, teacher_source TEXT,
            teacher_model TEXT, student_model TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        connection.execute("INSERT INTO mission_plans VALUES ('old','prompting','Tarea','80 %','sin nube',NULL,NULL,NULL,'old','old')")
    service = CoordinatorService(database)
    old = service.mission("old")
    assert (old["revision"], old["task"], old["constraints"]) == (1, "Tarea", "sin nube")
    updated = service.save_mission(mission_id="old", strategy="prompting", task="Continuar",
                                  success="90 %", expected_revision=1)
    assert updated["revision"] == 2
    assert CoordinatorService(database).mission("old")["task"] == "Continuar"


def test_restore_opens_reports_and_rebuilds_index_without_original_directory(tmp_path):
    original = tmp_path / "live"
    service = CoordinatorService(original / "state.db")
    vault = tmp_path / "vaults" / "Atlas"
    vault.mkdir(parents=True)
    (vault / "Atlas.md").write_text("# Equipo\nAna dirige el proyecto Atlas.", encoding="utf-8")
    snapshot = service.create_vault_snapshot(allowed_root=vault.parent, vault_name=vault.name)
    index = service.create_knowledge_index(snapshot_id=snapshot["record_id"])
    report = service.run_controlled_retrieval_benchmark(k=3)
    expected = service.product_artifact(report["record_id"])[0].read_bytes()
    archive = tmp_path / "backup.zip"
    create_backup(original / "state.db", archive)
    target = tmp_path / "restored"
    restore_backup(archive, target)
    original.rename(tmp_path / "unavailable")
    recovered = CoordinatorService(target / "state.db")
    artifact = recovered.product_artifact(report["record_id"])[0]
    assert artifact.is_relative_to(target)
    assert artifact.read_bytes() == expected
    assert recovered.repository.artifact_location(index["record_id"], expected_kind="knowledge_index").is_relative_to(target)
    rebuilt = recovered.create_knowledge_index(snapshot_id=snapshot["record_id"], previous_index_id=index["record_id"])
    assert rebuilt["status"] == "READY"


def test_legacy_backup_requires_origin_and_relocates_it_explicitly(tmp_path):
    original = tmp_path / "live"
    service = CoordinatorService(original / "state.db")
    report = service.run_controlled_retrieval_benchmark(k=2)
    modern = tmp_path / "v2.zip"
    create_backup(original / "state.db", modern)
    legacy = tmp_path / "v1.zip"
    with zipfile.ZipFile(modern) as source, zipfile.ZipFile(legacy, "w") as output:
        for name in source.namelist():
            data = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(data)
                manifest["format"] = "local-ai-lab.backup.v1"
                manifest.pop("artifact_locations")
                data = json.dumps(manifest).encode()
            output.writestr(name, data)
    with pytest.raises(ValueError, match="original_root"):
        restore_backup(legacy, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
    target = tmp_path / "restored"
    restore_backup(legacy, target, original_root=original)
    original.rename(tmp_path / "offline")
    assert CoordinatorService(target / "state.db").product_artifact(report["record_id"])[0].is_relative_to(target)


def _dataset_service(tmp_path):
    service = CoordinatorService(tmp_path / "state.db")
    service.record_product_item(record_id="snapshot-real", category="snapshot", title="Test",
                                status="COMPLETE", artifact_sha256="a" * 64, summary={})
    reviews = [_approved(service.feedback, run=f"run-{i}", case=f"private-{i}", reviewer="audit",
                         query=f"Pregunta privada {i}") for i in range(2)]
    return service, reviews


def test_dataset_revocation_during_build_publishes_nothing_and_consumes_no_other_approval(tmp_path, monkeypatch):
    service, reviews = _dataset_service(tmp_path)
    build = DatasetFactory.build
    def revoke_after_build(*args, **kwargs):
        result = build(*args, **kwargs)
        # A different Coordinator/session commits while the expensive build is running.
        other = CoordinatorService(service.repository.path)
        other.feedback.transition_training(reviews[1]["review_id"], to_state="rejected", actor="lead")
        return result
    monkeypatch.setattr(DatasetFactory, "build", revoke_after_build)
    with pytest.raises(FeedbackConflictError):
        service.build_approved_feedback_dataset(name="Rejected race", split_seed="fixed", actor="builder")
    assert service.product_workspace()["datasets"] == []
    assert list((tmp_path / "datasets").glob("dataset_*")) == []
    assert list((tmp_path / "packages").glob("dataset-*.zip")) == []
    assert service.feedback.get(reviews[0]["review_id"])["training_state"] == "approved"
    assert service.feedback.get(reviews[1]["review_id"])["training_state"] == "rejected"
    with service.repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_locations WHERE artifact_kind='training_dataset'").fetchone()[0] == 0


def test_dataset_publication_failure_rolls_back_all_export_events(tmp_path, monkeypatch):
    service, reviews = _dataset_service(tmp_path)
    def fail(**kwargs):
        raise OSError("simulated location persistence failure")
    monkeypatch.setattr(service.repository, "record_artifact_location", fail)
    with pytest.raises(OSError):
        service.build_approved_feedback_dataset(name="Disk failure", split_seed="fixed", actor="builder")
    assert service.product_workspace()["datasets"] == []
    assert list((tmp_path / "datasets").glob("dataset_*")) == []
    assert list((tmp_path / "packages").glob("dataset-*.zip")) == []
    for review in reviews:
        recovered = service.feedback.get(review["review_id"])
        assert recovered["training_state"] == "approved"
        assert not any(event["to_state"] == "exported" for event in recovered["events"])


def test_dataset_success_survives_restart_with_all_approvals_consumed(tmp_path):
    service, reviews = _dataset_service(tmp_path)
    dataset = service.build_approved_feedback_dataset(name="Approved", split_seed="fixed", actor="builder")
    reopened = CoordinatorService(service.repository.path)
    assert reopened.repository.product_record(dataset["record_id"])["status"] == "READY_FOR_TRAINING"
    assert all(reopened.feedback.get(review["review_id"])["training_state"] == "exported" for review in reviews)
    assert reopened.repository.artifact_location(dataset["record_id"], expected_kind="training_dataset").is_dir()


def test_lost_acknowledgement_after_dataset_commit_preserves_durable_files(tmp_path, monkeypatch):
    service, reviews = _dataset_service(tmp_path)
    publish = service._publish_feedback_dataset
    def committed_but_no_response(**kwargs):
        publish(**kwargs)
        raise OSError("lost acknowledgement after commit")
    monkeypatch.setattr(service, "_publish_feedback_dataset", committed_but_no_response)
    with pytest.raises(OSError, match="lost acknowledgement"):
        service.build_approved_feedback_dataset(name="Durable", split_seed="fixed", actor="builder")
    reopened = CoordinatorService(service.repository.path)
    dataset, = reopened.product_workspace()["datasets"]
    assert dataset["status"] == "READY_FOR_TRAINING"
    assert reopened.repository.artifact_location(dataset["record_id"], expected_kind="training_dataset").is_dir()
    assert (tmp_path / "packages" / f"dataset-{dataset['record_id']}.zip").is_file()
    assert all(reopened.feedback.get(review["review_id"])["training_state"] == "exported" for review in reviews)
