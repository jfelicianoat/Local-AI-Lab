from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter


def _review_fixture(tmp_path: Path):
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Atlas.md").write_text("# Owner\nAna Torres dirige Atlas.", encoding="utf-8")
    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=allowed, vault_root=vault),
        tmp_path / "snapshots", vault_id=str(uuid.uuid4()),
    )
    note = json.loads((snapshot.path / "notes.jsonl").read_text(encoding="utf-8"))
    chunk = json.loads((snapshot.path / "chunks.jsonl").read_text(encoding="utf-8"))
    response = {
        "answer": "Ana Torres dirige Atlas.",
        "findings": [{
            "claim": "Ana Torres dirige Atlas.",
            "evidence": [{
                "snapshot_id": snapshot.snapshot_id, "note_id": note["note_id"],
                "note_path": note["relative_path"], "section": chunk["section"],
                "chunk_id": chunk["chunk_id"],
                "source_reference": f"snapshot:sha256:{snapshot.global_hash}#chunk:{chunk['chunk_id']}",
            }],
        }],
        "contradictions": [], "uncertainties": [], "missing_information": [],
    }
    database = tmp_path / "coordinator.sqlite3"
    service = CoordinatorService(database)
    service.record_product_item(
        record_id=snapshot.snapshot_id, category="snapshot", title="Snapshot Test",
        status="COMPLETE", artifact_sha256=snapshot.global_hash,
        summary={"notes": 1, "read_only": True},
    )
    service.repository.record_artifact_location(
        record_id=snapshot.snapshot_id, artifact_kind="vault_snapshot",
        local_path=snapshot.path, artifact_sha256=snapshot.global_hash,
    )
    context = {
        "query": "¿Quién dirige Atlas?", "strategy_id": "R3.hybrid-rrf.v1",
        "model": "local/model", "prompt": "Responde con evidencia.",
        "retrieval_config": {"k": 5}, "snapshot_id": snapshot.snapshot_id,
        "retrieved_context": response["findings"][0]["evidence"],
        "estimated_tokens": 20,
        "cost": {"amount": None, "currency": "USD", "source": "not_available", "verification_status": "unknown"},
    }
    review = service.feedback.create_review(
        run_id="run-1", case_id="case-real", snapshot_id=snapshot.snapshot_id,
        reviewer="ana", run_context=context,
        original_response={**response, "answer": "Respuesta original."},
    )
    return service, review, response


def test_review_ui_api_verifies_diff_and_explicit_states(tmp_path: Path) -> None:
    service, review, corrected = _review_fixture(tmp_path)
    client = TestClient(create_app(service, app_token="desktop-token"))
    headers = {"X-App-Token": "desktop-token"}

    assert client.get("/app/v1/reviews").status_code == 401
    listed = client.get("/app/v1/reviews", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "draft"
    saved = client.put(
        f"/app/v1/reviews/{review['review_id']}/correction",
        headers=headers,
        json={"actor": "ana", "corrected_response": corrected},
    )
    assert saved.status_code == 200
    assert saved.json()["verification"]["deterministic_pass"] is True
    assert saved.json()["diff_text"]
    submitted = client.post(
        f"/app/v1/reviews/{review['review_id']}/state",
        headers=headers, json={"actor": "ana", "to_state": "submitted"},
    )
    assert submitted.json()["status"] == "submitted"
    accepted = client.post(
        f"/app/v1/reviews/{review['review_id']}/state",
        headers=headers, json={"actor": "lead", "to_state": "accepted"},
    )
    assert accepted.json()["status"] == "accepted"
    proposed = client.post(
        f"/app/v1/reviews/{review['review_id']}/training-state",
        headers=headers, json={"actor": "ana", "to_state": "proposed"},
    )
    assert proposed.json()["training_state"] == "proposed"


def test_knowledge_ui_discovers_snapshots_and_indexes_without_writing_vault(tmp_path: Path) -> None:
    allowed = tmp_path / "Vaults"
    vault = allowed / "Research"
    vault.mkdir(parents=True)
    note = vault / "Note.md"
    note.write_text("# Evidence\nRead only content.", encoding="utf-8")
    before = (note.read_bytes(), note.stat().st_mtime_ns)
    service = CoordinatorService(tmp_path / "app" / "coordinator.sqlite3")
    client = TestClient(create_app(service, app_token="desktop-token"))
    headers = {"X-App-Token": "desktop-token"}

    discovery = client.post(
        "/app/v1/vaults/discover", headers=headers, json={"allowed_root": str(allowed)}
    )
    assert discovery.status_code == 200
    assert discovery.json() == {"vaults": ["Research"]}
    snapshot = client.post(
        "/app/v1/snapshots", headers=headers,
        json={"allowed_root": str(allowed), "vault_name": "Research"},
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["category"] == "snapshot"
    assert snapshot.json()["summary"]["read_only"] is True
    index = client.post(
        "/app/v1/indexes", headers=headers,
        json={"snapshot_id": snapshot.json()["record_id"]},
    )
    assert index.status_code == 200
    assert index.json()["category"] == "index"
    assert (note.read_bytes(), note.stat().st_mtime_ns) == before
    assert service.repository.artifact_location(
        snapshot.json()["record_id"], expected_kind="vault_snapshot"
    ).is_dir()


def test_knowledge_ui_rejects_nested_or_traversal_vault_names(tmp_path: Path) -> None:
    allowed = tmp_path / "Vaults"
    (allowed / "Research").mkdir(parents=True)
    service = CoordinatorService(tmp_path / "app" / "coordinator.sqlite3")
    client = TestClient(create_app(service, app_token="desktop-token"))
    response = client.post(
        "/app/v1/snapshots", headers={"X-App-Token": "desktop-token"},
        json={"allowed_root": str(allowed), "vault_name": "../Research"},
    )
    assert response.status_code == 422
