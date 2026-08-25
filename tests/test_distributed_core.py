from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from local_ai_lab.coordinator.api import create_app
from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.coordinator.repository import CoordinatorConflict
from local_ai_lab.coordinator.service import (
    AuthenticationError,
    CoordinatorService,
    IdempotencyConflict,
)
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.storage.sqlite import ensure_local_database_path
from local_ai_lab.worker.runtime import WorkerRuntime


class TestProtector:
    __test__ = False

    def protect(self, value: str) -> bytes:
        return b"test-protected:" + base64.b64encode(value.encode())

    def unprotect(self, value: bytes) -> str:
        return base64.b64decode(value.removeprefix(b"test-protected:")).decode()


class ServiceTransport:
    def __init__(self, service: CoordinatorService, node_id: str, token: str) -> None:
        self.service = service
        self.node_id = node_id
        self.token = token
        self.online = True
        self.cancel_on_control = False

    def claim(self, *, idempotency_key: str) -> dict[str, Any] | None:
        self._connected()
        return self.service.claim_job(
            node_id=self.node_id,
            token=self.token,
            idempotency_key=idempotency_key,
        )

    def ack(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        self._connected()
        return self.service.ack_job(
            node_id=self.node_id,
            token=self.token,
            job_id=lease["job_id"],
            lease_token=lease["lease_token"],
            lease_generation=lease["lease_generation"],
            idempotency_key=idempotency_key,
        )

    def progress(
        self,
        lease: dict[str, Any],
        message: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._connected()
        return self.service.progress(
            node_id=self.node_id,
            token=self.token,
            job_id=lease["job_id"],
            lease_token=lease["lease_token"],
            lease_generation=lease["lease_generation"],
            sequence=message["sequence"],
            payload=message["payload"],
            idempotency_key=idempotency_key,
        )

    def complete(
        self,
        lease: dict[str, Any],
        message: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._connected()
        return self.service.complete_job(
            node_id=self.node_id,
            token=self.token,
            job_id=lease["job_id"],
            attempt_id=message["attempt_id"],
            lease_token=lease["lease_token"],
            lease_generation=message["lease_generation"],
            outcome=message["outcome"],
            payload=message["payload"],
            idempotency_key=idempotency_key,
        )

    def renew(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        self._connected()
        return self.service.renew_lease(
            node_id=self.node_id, token=self.token, job_id=lease["job_id"],
            lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
            lease_seconds=60, idempotency_key=idempotency_key,
        )

    def control(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        self._connected()
        if self.cancel_on_control:
            self.cancel_on_control = False
            self.service.request_cancel(
                job_id=lease["job_id"], idempotency_key=f"cancel:{lease['job_id']}"
            )
        return self.service.job_control(
            node_id=self.node_id, token=self.token, job_id=lease["job_id"],
            lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
            idempotency_key=idempotency_key,
        )

    def download_artifact(self, sha256: str) -> bytes:
        self._connected()
        return self.service.artifact_download(
            node_id=self.node_id, token=self.token, sha256=sha256
        ).read_bytes()

    def initiate_artifact(self, **kwargs: Any) -> dict[str, Any]:
        self._connected()
        return self.service.initiate_artifact_upload(
            node_id=self.node_id, token=self.token, **kwargs
        )

    def put_artifact_chunk(self, **kwargs: Any) -> dict[str, Any]:
        self._connected()
        return self.service.put_artifact_chunk(
            node_id=self.node_id, token=self.token, **kwargs
        )

    def commit_artifact(self, **kwargs: Any) -> dict[str, Any]:
        self._connected()
        return self.service.commit_artifact_upload(
            node_id=self.node_id, token=self.token, **kwargs
        )

    def _connected(self) -> None:
        if not self.online:
            raise ConnectionError("simulated disconnect")


def registered(service: CoordinatorService, node_id: str) -> tuple[str, ServiceTransport]:
    code = service.create_pairing_code()
    result = service.pair_and_register(
        pairing_code=code, node_id=node_id, hostname=f"host-{node_id}"
    )
    token = result["device_token"]
    service.heartbeat(node_id=node_id, token=token, capabilities={"facts": [], "workloads": []})
    return token, ServiceTransport(service, node_id, token)


def test_pairing_code_is_single_use_and_authentication_is_enforced(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    code = service.create_pairing_code()
    result = service.pair_and_register(
        pairing_code=code, node_id="node-1", hostname="host-1"
    )

    with pytest.raises(CoordinatorConflict):
        service.pair_and_register(
            pairing_code=code, node_id="node-2", hostname="host-2"
        )
    with pytest.raises(AuthenticationError):
        service.heartbeat(node_id="node-1", token="wrong", capabilities=None)

    assert service.heartbeat(
        node_id="node-1", token=result["device_token"], capabilities=None
    )["next_heartbeat_seconds"] == 15


def test_heartbeat_preserves_coordinator_workload_evidence(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    evidence = hashlib.sha256(b"successful benchmark").hexdigest()
    service.repository.record_workload_evidence(
        "worker", kind="embeddings.semantic", status="benchmarked",
        evidence_sha256=evidence,
    )

    service.heartbeat(
        node_id="worker", token=token,
        capabilities={
            "facts": [{"name": "gpu", "value": "test"}],
            "workloads": [
                {"kind": "embeddings.semantic", "status": "untested"},
                {"kind": "training.lora", "status": "tested"},
            ],
        },
    )

    record = service.repository.node_record("worker")
    assert record is not None
    capabilities = json.loads(record["capabilities_json"])
    by_kind = {item["kind"]: item for item in capabilities["workloads"]}
    assert by_kind["embeddings.semantic"]["status"] == "benchmarked"
    assert by_kind["embeddings.semantic"]["evidence_sha256"] == evidence
    assert by_kind["training.lora"]["status"] == "tested"


def test_authenticated_artifact_protocol_commits_verified_chunks(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    content = b"immutable worker result"
    digest = hashlib.sha256(content).hexdigest()
    upload = service.initiate_artifact_upload(
        node_id="worker", token=token, expected_sha256=digest,
        expected_size=len(content), chunk_size=8, idempotency_key="artifact-start",
    )
    for index, offset in enumerate(range(0, len(content), 8)):
        chunk = content[offset:offset + 8]
        service.put_artifact_chunk(
            node_id="worker", token=token, artifact_id=upload["artifact_id"],
            index=index, content=chunk, chunk_sha256=hashlib.sha256(chunk).hexdigest(),
            idempotency_key=f"artifact-chunk-{index}",
        )
    committed = service.commit_artifact_upload(
        node_id="worker", token=token, artifact_id=upload["artifact_id"],
        idempotency_key="artifact-commit",
    )

    assert committed["sha256"] == digest
    assert service.artifacts.verify(digest) is True


def test_job_runs_on_two_workers_without_shared_database(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator" / "state.db")
    _, transport_a = registered(service, "nvidia")
    _, transport_b = registered(service, "amd")
    for number in (1, 2):
        service.submit_job(
            JobSpec(kind="dry_run", payload={"number": number}), f"submit-{number}"
        )

    def execute(payload: dict[str, Any], progress: Any) -> dict[str, Any]:
        progress({"percent": 50})
        return {"echo": payload}

    worker_a = WorkerRuntime(
        node_id="nvidia",
        journal_path=tmp_path / "worker-nvidia" / "journal.db",
        transport=transport_a,
        executors={"dry_run": execute},
        secret_protector=TestProtector(),
    )
    worker_b = WorkerRuntime(
        node_id="amd",
        journal_path=tmp_path / "worker-amd" / "journal.db",
        transport=transport_b,
        executors={"dry_run": execute},
        secret_protector=TestProtector(),
    )

    assert worker_a.run_once("claim-a") == "succeeded"
    assert worker_b.run_once("claim-b") == "succeeded"
    assert worker_a.journal.path != worker_b.journal.path != service.repository.path


def test_worker_finishes_offline_and_syncs_after_reconnect(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    _, transport = registered(service, "worker")
    job = JobSpec(kind="disconnecting", payload={"value": 42})
    service.submit_job(job, "submit")
    worker: WorkerRuntime

    def execute(payload: dict[str, Any], progress: Any) -> dict[str, Any]:
        progress({"step": 1})
        transport.online = False
        return {"completed_offline": payload["value"]}

    worker = WorkerRuntime(
        node_id="worker",
        journal_path=tmp_path / "journal.db",
        transport=transport,
        executors={"disconnecting": execute},
        secret_protector=TestProtector(),
    )

    with pytest.raises(ConnectionError):
        worker.run_once("claim")
    assert worker.journal.job(job.job_id)["sync_state"] == "pending_result"
    assert len(worker.journal.pending_messages()) == 1

    transport.online = True
    assert worker.resume_sync(job.job_id) == 1
    assert worker.journal.pending_messages() == []
    assert service.repository.job(job.job_id)["state"] == "succeeded"


def test_worker_observes_coordinator_cancellation_and_syncs_terminal_state(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    _, transport = registered(service, "worker")
    transport.cancel_on_control = True
    job = JobSpec(kind="must-not-run", payload={})
    service.submit_job(job, "submit")
    executed = False

    def execute(payload: dict[str, Any], progress: Any) -> dict[str, Any]:
        nonlocal executed
        executed = True
        return {}

    worker = WorkerRuntime(
        node_id="worker", journal_path=tmp_path / "journal.db", transport=transport,
        executors={"must-not-run": execute}, secret_protector=TestProtector(),
    )

    assert worker.run_once("claim") == "cancelled"
    assert executed is False
    assert worker.journal.pending_messages() == []
    assert service.repository.job(job.job_id)["state"] == "cancelled"


def test_worker_materializes_cas_inputs_and_uploads_outputs_without_shared_paths(
    tmp_path: Path,
) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    _, transport = registered(service, "worker")
    source = tmp_path / "coordinator-source"
    source.mkdir()
    (source / "input.txt").write_text("private immutable input", encoding="utf-8")
    archive, digest = deterministic_zip(source, tmp_path / "input.zip")
    assert service.artifacts.ingest_file(archive)["sha256"] == digest
    spec = JobSpec(
        kind="cas-roundtrip",
        payload={
            "input_artifacts": [{
                "sha256": digest, "mount_as": "resolved_input", "archive": "zip",
            }],
            "output_mounts": ["output_dir"],
            "collect_outputs": [{"result_key": "output_dir", "kind": "result"}],
        },
    )
    service.submit_job(spec, "submit-cas")

    def execute(payload: dict[str, Any], progress: Any) -> dict[str, Any]:
        input_root = Path(payload["resolved_input"])
        output = Path(payload["output_dir"])
        output.mkdir(parents=True, exist_ok=False)
        (output / "result.txt").write_text(
            (input_root / "input.txt").read_text(encoding="utf-8").upper(),
            encoding="utf-8",
        )
        return {"output_dir": str(output), "summary": "done"}

    worker = WorkerRuntime(
        node_id="worker", journal_path=tmp_path / "worker" / "journal.db",
        transport=transport, executors={"cas-roundtrip": execute},
        secret_protector=TestProtector(),
    )
    assert worker.run_once("claim-cas") == "succeeded"
    stored = service.repository.job(spec.job_id)
    result = json.loads(stored["result_json"])
    assert result["summary"] == "done"
    assert "output_dir" not in result
    assert service.artifacts.verify(result["artifacts"][0]["sha256"])


def test_stale_fencing_result_is_preserved_but_not_promoted(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token_a, _ = registered(service, "a")
    token_b, _ = registered(service, "b")
    spec = JobSpec(kind="pure", payload={})
    service.submit_job(spec, "submit")
    old = service.claim_job(node_id="a", token=token_a, idempotency_key="claim-a")
    service.ack_job(
        node_id="a", token=token_a, job_id=spec.job_id,
        lease_token=old["lease_token"], lease_generation=old["lease_generation"],
        idempotency_key="ack-a",
    )
    service.repository.expire_leases(datetime.now(UTC) + timedelta(hours=1))
    service.repository.reconcile_orphan(spec.job_id, "requeue")
    current = service.claim_job(node_id="b", token=token_b, idempotency_key="claim-b")

    stale = service.complete_job(
        node_id="a", token=token_a, job_id=spec.job_id,
        attempt_id=old["attempt_id"], lease_token=old["lease_token"],
        lease_generation=old["lease_generation"], outcome="succeeded",
        payload={"from": "old"}, idempotency_key="complete-old",
    )

    assert stale["classification"] == "stale_attempt"
    assert service.repository.job(spec.job_id)["attempt_id"] == current["attempt_id"]
    assert service.repository.job(spec.job_id)["result_json"] is None


def test_claim_filters_jobs_by_tested_capabilities(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "cpu-only")
    service.heartbeat(
        node_id="cpu-only",
        token=token,
        capabilities={
            "facts": [{"key": "compute.backend", "value": "cpu", "status": "detected"}],
            "workloads": [{"kind": "inference", "status": "tested"}],
        },
    )
    service.submit_job(
        JobSpec(
            kind="gpu",
            payload={},
            requirements={"required_facts": {"compute.backend": "cuda"}},
        ),
        "submit-gpu",
    )

    assert service.claim_job(
        node_id="cpu-only", token=token, idempotency_key="claim"
    ) is None


def test_claim_honors_explicit_node_allowlist(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token_a, _ = registered(service, "node-a")
    token_b, _ = registered(service, "node-b")
    service.submit_job(
        JobSpec(kind="restricted", payload={}, requirements={"node_ids": ["node-b"]}),
        "submit-restricted",
    )

    assert service.claim_job(
        node_id="node-a", token=token_a, idempotency_key="claim-a"
    ) is None
    lease = service.claim_job(
        node_id="node-b", token=token_b, idempotency_key="claim-b"
    )
    assert lease is not None
    assert lease["node_id"] == "node-b"


def test_idempotency_replays_same_response_and_rejects_changed_request(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    first = JobSpec(kind="a", payload={})
    second = JobSpec(kind="b", payload={})

    response = service.submit_job(first, "same-key")
    assert service.submit_job(first, "same-key") == response
    with pytest.raises(IdempotencyConflict):
        service.submit_job(second, "same-key")


def test_network_sqlite_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="network/UNC"):
        ensure_local_database_path(Path(r"\\server\share\state.db"))


def test_protocol_api_requires_auth_and_idempotency(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    code = service.create_pairing_code()
    client = TestClient(create_app(service))
    paired = client.post(
        "/node/v1/pair",
        json={
            "pairing_code": code,
            "node_id": "api-worker",
            "hostname": "api-host",
            "protocol_min": 1,
            "protocol_max": 1,
        },
    )

    assert paired.status_code == 200
    assert client.post("/node/v1/jobs/claim", json={}).status_code == 422
    headers = {
        "X-Node-ID": "api-worker",
        "Authorization": f"Bearer {paired.json()['device_token']}",
        "Idempotency-Key": "api-claim",
    }
    response = client.post("/node/v1/jobs/claim", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"lease": None}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_api_rejects_unknown_fields(tmp_path: Path) -> None:
    client = TestClient(create_app(CoordinatorService(tmp_path / "coordinator.db")))
    response = client.post(
        "/node/v1/pair",
        json={
            "pairing_code": "12345678",
            "node_id": "n",
            "hostname": "h",
            "unexpected": True,
        },
    )
    assert response.status_code == 422


def test_desktop_overview_requires_ephemeral_app_token(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    client = TestClient(create_app(service, app_token="desktop-session-secret"))

    assert client.get("/app/v1/overview").status_code == 401
    response = client.get(
        "/app/v1/overview", headers={"X-App-Token": "desktop-session-secret"}
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "local-ai-lab.overview.v1"
    assert response.json()["external_dependencies"]["ai_broker"] == "unknown"
    assert response.json()["evidence"][0]["status"] == "pending"


def test_desktop_workspace_is_authenticated_and_contains_only_registered_records(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    service.record_product_item(
        record_id="snapshot-1", category="snapshot", title="Vault Research",
        status="COMPLETE", artifact_sha256="a" * 64,
        summary={"notes": 42, "read_only": True},
    )
    client = TestClient(create_app(service, app_token="desktop-session-secret"))

    assert client.get("/app/v1/workspace").status_code == 401
    response = client.get(
        "/app/v1/workspace", headers={"X-App-Token": "desktop-session-secret"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "local-ai-lab.workspace.v1"
    assert payload["knowledge"][0]["record_id"] == "snapshot-1"
    assert payload["knowledge"][0]["summary"]["read_only"] is True
    assert payload["datasets"] == []


def test_phase_evidence_requires_recoverable_artifact_hash(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    with pytest.raises(ValueError):
        service.record_phase_evidence(
            evidence_id="phase1.core",
            label="Núcleo distribuido",
            status="tested",
            artifact_sha256="not-a-hash",
            source_reference="artifacts/phase1/report.json",
            observed_at="2026-08-23T00:00:00Z",
        )

    digest = "a" * 64
    service.record_phase_evidence(
        evidence_id="phase1.core",
        label="Núcleo distribuido",
        status="tested",
        artifact_sha256=digest,
        source_reference="artifacts/phase1/report.json",
        observed_at="2026-08-23T00:00:00Z",
    )
    evidence = service.overview()["evidence"][0]
    assert evidence["status"] == "tested"
    assert evidence["artifact_sha256"] == digest
