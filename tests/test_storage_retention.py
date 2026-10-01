from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.coordinator.repository import CoordinatorConflict


def _age(path: Path) -> None:
    old = (datetime.now(UTC) - timedelta(days=90)).timestamp()
    if path.is_dir():
        manifest = path / "manifest.json"
        data = json.loads(manifest.read_text())
        data["created_at"] = datetime.fromtimestamp(old, UTC).isoformat()
        manifest.write_text(json.dumps(data))
        for item in path.rglob("*"):
            os.utime(item, (old, old))
    os.utime(path, (old, old))


def _blob(service: CoordinatorService, content: bytes = b"orphan") -> tuple[str, str]:
    source = service.repository.path.parent / "source.bin"
    source.write_bytes(content)
    result = service.artifacts.ingest_file(source)
    _age(service.artifacts.blob_path(result["sha256"]))
    _age(service.artifacts.uploads / result["artifact_id"])
    return result["sha256"], result["artifact_id"]


def test_cleanup_only_removes_reviewed_old_orphans_and_replays(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    fresh = service.artifacts.initiate(expected_sha256="a" * 64, expected_size=4, chunk_size=4)
    abandoned = service.artifacts.initiate(expected_sha256="b" * 64, expected_size=5, chunk_size=5)
    service.artifacts.put_chunk(artifact_id=abandoned.artifact_id, index=0, content=b"chunk",
                               chunk_sha256=hashlib.sha256(b"chunk").hexdigest())
    _age(service.artifacts.uploads / abandoned.artifact_id)
    plan = service.storage_cleanup_plan()
    assert {(item["kind"], item["id"]) for item in plan["entries"]} == {
        ("blob", digest), ("upload", upload), ("upload", abandoned.artifact_id)}
    assert service.artifacts.verify(digest)  # Planning has no deletion side effects.
    result = service.apply_storage_cleanup(plan["plan_id"])
    assert result["removed_count"] == 3 and result["skipped_count"] == 0
    assert service.apply_storage_cleanup(plan["plan_id"]) == result
    assert not service.artifacts.blob_path(digest).exists()
    assert (service.artifacts.uploads / fresh.artifact_id).exists()
    assert service.artifacts.usage()["pending_reserved_bytes"] == 4
    with pytest.raises(CoordinatorConflict, match="retired"):
        service.repository.require_upload_not_retired(upload)


@pytest.mark.parametrize("table,columns", [
    ("product_records", "record_id,category,title,status,artifact_sha256,summary_json,created_at,updated_at"),
    ("phase_evidence", "evidence_id,label,status,artifact_sha256,source_reference,observed_at"),
    ("jobs", "job_id,spec_json,spec_fingerprint,state,created_at,updated_at"),
    ("training_checkpoints", "checkpoint_id,job_id,attempt_id,lease_generation,node_id,step,artifact_id,artifact_sha256,created_at"),
])
def test_durable_evidence_protects_blobs(tmp_path: Path, table: str, columns: str) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    with service.repository.transaction() as db:
        if table == "product_records":
            values = ("dataset", "dataset", "Dataset", "COMPLETE", digest, "{}", "old", "old")
        elif table == "phase_evidence":
            values = ("evidence", "Evidence", "tested", digest, "test", "old")
        elif table == "jobs":
            values = ("job", json.dumps({"payload": {"input_artifacts": [{"sha256": digest}]}}),
                      "f" * 64, "failed", "old", "old")
        else:
            db.execute("INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,created_at,updated_at) "
                       "VALUES ('job','{}','x','needs_review','old','old')")
            values = ("cp", "job", "attempt", 1, "node", 10, upload, digest, "old")
        db.execute(f"INSERT INTO {table}({columns}) VALUES ({','.join('?' for _ in values)})", values)
    plan = service.storage_cleanup_plan()
    assert not any(item["kind"] == "blob" for item in plan["entries"])
    service.apply_storage_cleanup(plan["plan_id"])
    assert service.artifacts.verify(digest)


def test_new_reference_invalidates_review_before_any_deletion(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    plan = service.storage_cleanup_plan()
    with service.repository.transaction() as db:
        db.execute("INSERT INTO phase_evidence VALUES ('new','New','tested',?,'test','now')", (digest,))
    with pytest.raises(CoordinatorConflict, match="ha cambiado"):
        service.apply_storage_cleanup(plan["plan_id"])
    assert service.artifacts.verify(digest)
    assert (service.artifacts.uploads / upload).exists()
    service.repository.require_upload_not_retired(upload)


def test_active_attempt_and_recent_upload_protect_old_digest(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    with service.repository.transaction() as db:
        db.execute("INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,created_at,updated_at) "
                   "VALUES ('job','{}','x','needs_review','old','old')")
        db.execute("INSERT INTO artifact_upload_owners VALUES (?, 'node','job','attempt',1,?,'old')",
                   (upload, digest))
    assert not service.storage_cleanup_plan()["entries"]
    with service.repository.transaction() as db:
        db.execute("UPDATE jobs SET state='failed'")
    fresh = service.artifacts.initiate(expected_sha256=digest, expected_size=len(b"orphan"), chunk_size=6)
    plan = service.storage_cleanup_plan()
    assert not any(item["kind"] == "blob" for item in plan["entries"])
    assert not any(item["id"] == fresh.artifact_id for item in plan["entries"])


def test_cleanup_resumes_after_partial_directory_deletion(tmp_path: Path, monkeypatch) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    plan = service.storage_cleanup_plan()
    real_rmtree = shutil.rmtree
    def interrupted(path):
        (path / "manifest.json").unlink()
        raise OSError("simulated interruption")
    monkeypatch.setattr("local_ai_lab.maintenance.retention.shutil.rmtree", interrupted)
    with pytest.raises(OSError, match="interruption"):
        service.apply_storage_cleanup(plan["plan_id"])
    with pytest.raises(CoordinatorConflict, match="retired"):
        service.repository.require_upload_not_retired(upload)
    assert service.artifacts.usage()["cleanup_pending_bytes"] > 0
    assert service.pending_storage_cleanup()["status"] == "applying"
    assert service.storage_cleanup_plan()["plan_id"] == plan["plan_id"]
    monkeypatch.setattr("local_ai_lab.maintenance.retention.shutil.rmtree", real_rmtree)
    restarted = CoordinatorService(service.repository.path)
    result = restarted.apply_storage_cleanup(plan["plan_id"])
    assert result["removed_count"] == 2 and result["skipped_count"] == 0
    assert not restarted.artifacts.blob_path(digest).exists()
    assert restarted.artifacts.usage()["cleanup_pending_bytes"] == 0
    assert restarted.pending_storage_cleanup() is None


def test_cleanup_api_requires_session_and_explicit_confirmation(tmp_path: Path) -> None:
    from local_ai_lab.coordinator.api import create_app
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    _blob(service)
    client = TestClient(create_app(service, app_token="session"))
    assert client.post("/app/v1/storage/cleanup/plan", json={}).status_code == 401
    assert client.get("/app/v1/storage/cleanup/pending").status_code == 401
    headers = {"X-App-Token": "session"}
    plan = client.post("/app/v1/storage/cleanup/plan", headers=headers, json={}).json()
    assert client.post("/app/v1/storage/cleanup/apply", headers=headers,
                       json={"plan_id": plan["plan_id"], "confirmed": False}).status_code == 422
    result = client.post("/app/v1/storage/cleanup/apply", headers=headers,
                         json={"plan_id": plan["plan_id"], "confirmed": True})
    assert result.status_code == 200 and result.json()["removed_count"] == 2


def test_changed_upload_and_expired_plan_cannot_delete(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    plan = service.storage_cleanup_plan()
    (service.artifacts.uploads / upload / "new.chunk").write_bytes(b"new data")
    with pytest.raises(CoordinatorConflict, match="ha cambiado"):
        service.apply_storage_cleanup(plan["plan_id"])
    assert service.artifacts.verify(digest)
    plan = service.storage_cleanup_plan()
    plan["created_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with service.repository.transaction() as db:
        db.execute("UPDATE storage_cleanup_plans SET plan_json=? WHERE plan_id=?",
                   (json.dumps(plan), plan["plan_id"]))
    with pytest.raises(CoordinatorConflict, match="caducado"):
        service.apply_storage_cleanup(plan["plan_id"])


def test_retired_upload_response_cannot_be_reused_for_new_job(tmp_path: Path) -> None:
    from local_ai_lab.domain.common import canonical_json, sha256_text, utc_timestamp
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    service.apply_storage_cleanup(service.storage_cleanup_plan()["plan_id"])
    service.repository.register_node(node_id="node", hostname="worker", protocol_min=1,
                                     protocol_max=1, auth_token="credential")
    request = {"expected_sha256": digest, "expected_size": 6, "chunk_size": 6}
    with service.repository.transaction() as db:
        db.execute("INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,assigned_node_id,"
                   "lease_expires_at,created_at,updated_at) VALUES ('new',?,'x','running','node',?,'now','now')",
                   (json.dumps({"payload": {"collect_outputs": True}}),
                    (datetime.now(UTC) + timedelta(hours=1)).isoformat()))
        db.execute("INSERT INTO idempotency VALUES (?,?,?,?,?)", (
            "node:node:artifact:initiate", "old", sha256_text(canonical_json(request)),
            json.dumps({"artifact_id": upload}), utc_timestamp()))
    with pytest.raises(CoordinatorConflict, match="retired"):
        service.initiate_artifact_upload(node_id="node", token="credential",
                                         idempotency_key="old", **request)


def test_retention_skips_linked_upload_tree(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.sqlite")
    digest, upload = _blob(service)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "preserve.txt").write_text("keep")
    link = service.artifacts.uploads / upload / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink permission unavailable")
    plan = service.storage_cleanup_plan()
    assert not plan["entries"]
    assert service.artifacts.verify(digest)
    assert (outside / "preserve.txt").read_text() == "keep"
