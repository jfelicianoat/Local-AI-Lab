from __future__ import annotations

import base64
import hashlib
import json
import time
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
from local_ai_lab.domain.jobs import IdempotencyClass, JobSpec, ReassignmentPolicy
from local_ai_lab.storage.sqlite import ensure_local_database_path
from local_ai_lab.worker.runtime import WorkerRuntime
from local_ai_lab.worker.journal import WorkerJournal
from local_ai_lab.worker.http_transport import CoordinatorTransportError
from local_ai_lab.training.checkpoints import create_checkpoint_bundle


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

    def publish_checkpoint(
        self, lease: dict[str, Any], *, step: int, artifact_id: str,
        artifact_sha256: str, idempotency_key: str,
    ) -> dict[str, Any]:
        self._connected()
        return self.service.publish_training_checkpoint(
            node_id=self.node_id, token=self.token, job_id=lease["job_id"],
            attempt_id=lease["attempt_id"], lease_token=lease["lease_token"],
            lease_generation=lease["lease_generation"], step=step,
            artifact_id=artifact_id, artifact_sha256=artifact_sha256,
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


@pytest.mark.parametrize("training_kind", ["training.lora.v1", "training.distillation.v1"])
def test_training_checkpoint_survives_lost_publication_response(
    tmp_path: Path, training_kind: str,
) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")

    class LostPublication(ServiceTransport):
        lost = False

        def publish_checkpoint(self, lease: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            response = super().publish_checkpoint(lease, **kwargs)
            if not self.lost:
                self.lost = True
                self.online = False
                raise ConnectionError("simulated lost checkpoint response")
            return response

    transport = LostPublication(service, "worker", token)
    spec = JobSpec(
        kind=training_kind,
        payload={
            "dataset_fingerprint": "b" * 64,
            "base_model": "local/base",
            "student_model": "local/student",
            "chat_template_fingerprint": "d" * 64,
            "collect_outputs": [{"result_key": "output_dir", "kind": "training_result"}],
        },
        idempotency_class=IdempotencyClass.CHECKPOINTABLE,
        reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
    )
    service.submit_job(spec, "submit-checkpoint")

    def execute(payload: dict[str, Any], progress: Any) -> dict[str, Any]:
        source = tmp_path / "checkpoint-4"
        source.mkdir()
        (source / "trainer_state.json").write_text('{"global_step":4}', encoding="utf-8")
        (source / "optimizer.pt").write_bytes(b"optimizer")
        (source / "scheduler.pt").write_bytes(b"scheduler")
        (source / "adapter_model.safetensors").write_bytes(b"weights")
        if training_kind == "training.distillation.v1":
            (source / "distilled-train.jsonl").write_text('{"messages":[]}\n', encoding="utf-8")
            (source / "teacher-evidence.json").write_text('{}\n', encoding="utf-8")
        bundle, digest = create_checkpoint_bundle(
            source, tmp_path / "checkpoint.zip",
            metadata={
                **payload["_worker_attempt"],
                "dataset_fingerprint": payload["dataset_fingerprint"],
                "model_id": (payload["base_model"] if training_kind == "training.lora.v1"
                             else payload["student_model"]),
                "base_weights_sha256": "c" * 64,
                "chat_template_fingerprint": payload["chat_template_fingerprint"],
            }, step=4,
        )
        progress({
            "stage": "checkpoint", "step": 4,
            "_checkpoint_artifact": {
                "kind": "training_checkpoint", "local_path": str(bundle),
                "sha256": digest, "size": bundle.stat().st_size,
                "media_type": "application/zip",
            },
        })
        raise RuntimeError("simulate interrupted training")

    worker = WorkerRuntime(
        node_id="worker", journal_path=tmp_path / "worker.db",
        transport=transport, executors={training_kind: execute},
        secret_protector=TestProtector(), lease_keepalive_seconds=100,
    )
    with pytest.raises(ConnectionError, match="simulated disconnect"):
        worker.run_once("claim-checkpoint")
    assert len(service.training_checkpoints(spec.job_id)) == 1
    pending = worker.journal.pending_messages()
    assert pending[0]["kind"] == "checkpoint"
    assert "local_path" not in pending[0]["payload_json"]
    transport.online = True
    assert worker.sync_all_pending() >= 1
    checkpoints = service.training_checkpoints(spec.job_id)
    assert len(checkpoints) == 1
    checkpoint_id = checkpoints[0]["checkpoint_id"]
    target_node_id = "other-worker" if training_kind == "training.distillation.v1" else "worker"
    resumed_transport = transport
    if target_node_id != "worker":
        other_token, resumed_transport = registered(service, target_node_id)
    client = TestClient(create_app(service, app_token="test-desktop-session"))
    route = f"/app/v1/jobs/{spec.job_id}/checkpoints"
    assert client.get(route).status_code == 401
    assert client.get(route, headers={"X-App-Token": "test-desktop-session"}).json()[0][
        "checkpoint_id"
    ] == checkpoint_id
    assert client.post(
        f"/app/v1/jobs/{spec.job_id}/resume-checkpoint",
        headers={"X-App-Token": "wrong"},
        json={"checkpoint_id": checkpoint_id, "idempotency_key": "operator-approved-recovery",
              "node_id": target_node_id},
    ).status_code == 401
    response = client.post(
        f"/app/v1/jobs/{spec.job_id}/resume-checkpoint",
        headers={"X-App-Token": "test-desktop-session"},
        json={"checkpoint_id": checkpoint_id, "idempotency_key": "operator-approved-recovery",
              "node_id": target_node_id},
    )
    assert response.status_code == 200
    resumed = response.json()
    assert resumed["job_id"] != spec.job_id
    assert service.repository.job(resumed["job_id"])["state"] == "ready"
    assert json.loads(service.repository.job(resumed["job_id"])["spec_json"])[
        "requirements"
    ]["node_ids"] == [target_node_id]
    assert service.resume_training_from_checkpoint(
        job_id=spec.job_id, checkpoint_id=checkpoint_id,
        idempotency_key="operator-approved-recovery", node_id=target_node_id,
    )["job_id"] == resumed["job_id"]
    with pytest.raises(CoordinatorConflict, match="already has an approved recovery"):
        service.resume_training_from_checkpoint(
            job_id=spec.job_id, checkpoint_id=checkpoint_id,
            idempotency_key="different-approval", node_id=target_node_id,
        )
    with pytest.raises(CoordinatorConflict, match="already has an approved recovery"):
        service.restart_training_job(
            job_id=spec.job_id, node_id=target_node_id,
            idempotency_key="restart-after-resume",
        )

    observed: dict[str, Any] = {}

    def inspect_recovery(payload: dict[str, Any], progress: Any) -> dict[str, Any]:
        observed.update(payload)
        checkpoint_dir = Path(payload["resume_from_checkpoint"])
        assert json.loads((checkpoint_dir / "trainer_state.json").read_text())["global_step"] == 4
        if training_kind == "training.distillation.v1":
            assert (checkpoint_dir / "distilled-train.jsonl").is_file()
            assert (checkpoint_dir / "teacher-evidence.json").is_file()
        raise RuntimeError("stop before loading a real model")

    resume_worker = (worker if target_node_id == "worker" else WorkerRuntime(
        node_id=target_node_id, journal_path=tmp_path / "resumed-worker.db",
        transport=resumed_transport, executors={},
        secret_protector=TestProtector(), lease_keepalive_seconds=100,
    ))
    resume_worker.executors[training_kind] = inspect_recovery
    assert resume_worker.run_once("claim-resumed-checkpoint") == "failed"
    assert observed["expected_base_weights_sha256"] == "c" * 64
    assert observed["resume_checkpoint"]["source_job_id"] == spec.job_id


def test_training_without_checkpoint_can_restart_on_compatible_worker(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    original_token, original_transport = registered(service, "original")
    other_token, _ = registered(service, "other")
    service.heartbeat(node_id="original", token=original_token, capabilities={
        "facts": [{"key": "gpu.backend", "value": "cuda"}], "workloads": [],
    })
    spec = JobSpec(
        kind="training.lora.v1",
        payload={"base_model": "local/base", "input_artifacts": []},
        requirements={"node_ids": ["original"], "required_facts": {"gpu.backend": "cuda"}},
        idempotency_class=IdempotencyClass.CHECKPOINTABLE,
        reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
    )
    service.submit_job(spec, "submit-uncheckpointed")

    def fail(_payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        raise RuntimeError("training interrupted before first save")

    worker = WorkerRuntime(
        node_id="original", journal_path=tmp_path / "original.db",
        transport=original_transport, executors={spec.kind: fail},
        secret_protector=TestProtector(), lease_keepalive_seconds=100,
    )
    assert worker.run_once("claim-uncheckpointed") == "failed"
    assert service.training_checkpoints(spec.job_id) == []
    with pytest.raises(ValueError, match="lacks training evidence"):
        service.restart_training_job(
            job_id=spec.job_id, node_id="other", idempotency_key="restart-approved",
        )
    service.heartbeat(node_id="other", token=other_token, capabilities={
        "facts": [{"key": "gpu.backend", "value": "cuda"}], "workloads": [],
    })
    client = TestClient(create_app(service, app_token="test-desktop-session"))
    route = f"/app/v1/jobs/{spec.job_id}/restart-training"
    body = {"node_id": "other", "idempotency_key": "restart-approved"}
    assert client.post(route, json=body).status_code == 401
    response = client.post(route, json=body, headers={"X-App-Token": "test-desktop-session"})
    assert response.status_code == 200
    restarted = response.json()
    status_response = client.get(
        f"/app/v1/jobs/{spec.job_id}/training-restart",
        headers={"X-App-Token": "test-desktop-session"},
    )
    assert status_response.json()["restarted_job_id"] == restarted["job_id"]
    replacement = service.repository.job(restarted["job_id"])
    assert replacement["state"] == "ready"
    replacement_spec = json.loads(replacement["spec_json"])
    assert replacement_spec["requirements"]["node_ids"] == ["other"]
    assert "resume_checkpoint" not in replacement_spec["payload"]
    assert service.restart_training_job(
        job_id=spec.job_id, node_id="other", idempotency_key="restart-approved",
    )["job_id"] == restarted["job_id"]


def test_training_needing_review_can_be_cancelled(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, transport = registered(service, "worker")
    spec = JobSpec(
        kind="training.lora.v1", payload={},
        idempotency_class=IdempotencyClass.CHECKPOINTABLE,
        reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
    )
    service.submit_job(spec, "submit-review-cancel")
    service.record_product_item(
        record_id=spec.job_id, category="training", title="Entrenamiento de prueba",
        status="TRAINING_QUEUED", artifact_sha256=spec.fingerprint(), summary={},
    )
    lease = transport.claim(idempotency_key="claim-review-cancel")
    assert lease is not None
    transport.ack(lease, idempotency_key="ack-review-cancel")
    service.repository.expire_leases(datetime.now(UTC) + timedelta(hours=1))
    service.repository.reconcile_orphan(spec.job_id, "needs_review")
    cancelled = service.request_cancel(
        job_id=spec.job_id, idempotency_key="operator-discard-review",
    )
    assert cancelled["state"] == "cancelled"
    assert service.repository.product_record(spec.job_id)["status"] == "CANCELLED"


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
    # A heartbeat's claim is not accepted job evidence.
    assert by_kind["training.lora"]["status"] == "untested"


def test_authenticated_artifact_protocol_commits_verified_chunks(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    job = JobSpec(
        kind="artifact-test",
        payload={"collect_outputs": [{"result_key": "file", "kind": "test_result"}]},
        requirements={"node_ids": ["worker"]},
    )
    service.submit_job(job, "artifact-test-submit")
    lease = service.claim_job(node_id="worker", token=token, idempotency_key="artifact-test-claim")
    assert lease is not None
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


def test_paired_node_without_assigned_job_cannot_download_private_artifact(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "unassigned")
    source = tmp_path / "private.bin"
    source.write_bytes(b"private input")
    digest = service.artifacts.ingest_file(source)["sha256"]
    with pytest.raises(CoordinatorConflict, match="not authorized"):
        service.artifact_download(node_id="unassigned", token=token, sha256=digest)


def test_success_without_declared_result_artifact_cannot_be_promoted(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    spec = JobSpec(
        kind="strategy.suite.v1",
        payload={"collect_outputs": [{"result_key": "report_dir", "kind": "strategy_suite_report"}]},
        requirements={"node_ids": ["worker"]},
    )
    service.submit_job(spec, "submit-experiment")
    service.record_product_item(
        record_id=spec.job_id, category="experiment", title="Test strategy",
        status="EXPERIMENT_QUEUED", artifact_sha256=spec.fingerprint(), summary={},
    )
    lease = service.claim_job(node_id="worker", token=token, idempotency_key="claim-experiment")
    assert lease is not None
    service.ack_job(
        node_id="worker", token=token, job_id=spec.job_id,
        lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
        idempotency_key="ack-experiment",
    )
    with pytest.raises(ValueError, match="requires every declared result artifact"):
        service.complete_job(
            node_id="worker", token=token, job_id=spec.job_id,
            attempt_id=lease["attempt_id"], lease_token=lease["lease_token"],
            lease_generation=lease["lease_generation"], outcome="succeeded",
            payload={"strategy_id": "B1"}, idempotency_key="complete-experiment",
        )
    assert service.repository.job(spec.job_id)["state"] == "acknowledged"
    assert service.repository.product_record(spec.job_id)["status"] == "EXPERIMENT_QUEUED"


def test_cancellation_after_execution_starts_reaches_worker(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    _, transport = registered(service, "worker")
    spec = JobSpec(kind="cancel-during-execution", payload={})
    service.submit_job(spec, "submit-cancel-later")
    def execute(payload: dict[str, Any], progress: Any) -> dict[str, Any]:
        progress({"step": 1})
        service.request_cancel(job_id=spec.job_id, idempotency_key="cancel-after-step")
        progress({"step": 2})
        return {"should_not_finish": True}
    worker = WorkerRuntime(
        node_id="worker", journal_path=tmp_path / "worker.db", transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    assert worker.run_once("claim-cancel-later") == "cancelled"
    assert service.repository.job(spec.job_id)["state"] == "cancelled"


def test_long_running_executor_renews_lease_without_progress_callbacks(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    spec = JobSpec(kind="slow-pure-job", payload={})
    service.submit_job(spec, "submit-slow")

    class CountingTransport(ServiceTransport):
        renewals = 0

        def renew(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
            self.renewals += 1
            return super().renew(lease, idempotency_key=idempotency_key)

    transport = CountingTransport(service, "worker", token)

    def execute(_payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        time.sleep(0.12)
        return {"completed": True}

    worker = WorkerRuntime(
        node_id="worker", journal_path=tmp_path / "worker.db", transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
        lease_keepalive_seconds=0.02,
    )
    assert worker.run_once("claim-slow") == "succeeded"
    assert transport.renewals >= 2
    assert service.repository.job(spec.job_id)["state"] == "succeeded"


def test_expired_attempt_is_fenced_and_same_worker_accepts_new_generation(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    spec = JobSpec(kind="pure-reassign", payload={})
    service.submit_job(spec, "submit-reassign")
    old = service.claim_job(node_id="worker", token=token, idempotency_key="claim-old")
    assert old is not None
    journal = WorkerJournal(tmp_path / "journal.db", TestProtector())
    journal.accept_lease(old)
    with service.repository.transaction() as db:
        db.execute(
            "UPDATE jobs SET lease_expires_at=? WHERE job_id=?",
            ("2000-01-01T00:00:00Z", spec.job_id),
        )
    stale = service.complete_job(
        node_id="worker", token=token, job_id=spec.job_id,
        attempt_id=old["attempt_id"], lease_token=old["lease_token"],
        lease_generation=old["lease_generation"], outcome="succeeded",
        payload={}, idempotency_key="stale-completion",
    )
    assert stale["accepted"] is False
    current = service.claim_job(node_id="worker", token=token, idempotency_key="claim-new")
    assert current is not None and current["lease_generation"] == 2
    assert journal.accept_lease(current)["replayed"] is False
    assert journal.lease(spec.job_id)["attempt_id"] == current["attempt_id"]


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


@pytest.mark.parametrize("response_lost", [False, True])
def test_worker_restarts_after_accept_or_lost_ack(tmp_path: Path, response_lost: bool) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    spec = JobSpec(kind="restartable", payload={})
    service.submit_job(spec, "submit-restartable")

    class InterruptedAck(ServiceTransport):
        interrupted = False

        def ack(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
            if not self.interrupted:
                self.interrupted = True
                if response_lost:
                    super().ack(lease, idempotency_key=idempotency_key)
                raise ConnectionError("simulated crash around ack")
            return super().ack(lease, idempotency_key=idempotency_key)

    transport = InterruptedAck(service, "worker", token)
    executions = 0

    def execute(_payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        nonlocal executions
        executions += 1
        return {"value": 42}

    journal_path = tmp_path / "worker.db"
    worker = WorkerRuntime(
        node_id="worker", journal_path=journal_path, transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    with pytest.raises(ConnectionError):
        worker.run_once("claim-before-ack")
    assert worker.journal.job(spec.job_id)["local_state"] == "accepted"
    restarted = WorkerRuntime(
        node_id="worker", journal_path=journal_path, transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    assert restarted.recover_incomplete() == "succeeded"
    assert executions == 1
    assert service.repository.job(spec.job_id)["state"] == "succeeded"


def test_worker_restarts_pure_execution_in_a_new_output_directory(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    _, transport = registered(service, "worker")
    spec = JobSpec(kind="restartable-output", payload={"output_mounts": ["output_dir"]})
    service.submit_job(spec, "submit-output")
    outputs: list[Path] = []

    def execute(payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        output = Path(payload["output_dir"])
        output.mkdir(parents=True)
        outputs.append(output)
        if len(outputs) == 1:
            raise SystemExit("simulated process loss during execution")
        return {"recovered": True}

    journal_path = tmp_path / "worker.db"
    worker = WorkerRuntime(
        node_id="worker", journal_path=journal_path, transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    with pytest.raises(SystemExit):
        worker.run_once("claim-output")
    assert worker.journal.job(spec.job_id)["local_state"] == "running"
    restarted = WorkerRuntime(
        node_id="worker", journal_path=journal_path, transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    assert restarted.recover_incomplete() == "succeeded"
    assert len(outputs) == 2 and outputs[0] != outputs[1]
    assert service.repository.job(spec.job_id)["state"] == "succeeded"


def test_worker_restart_does_not_repeat_checkpointable_training(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    _, transport = registered(service, "worker")
    spec = JobSpec(
        kind="training.lora.v1", payload={},
        idempotency_class=IdempotencyClass.CHECKPOINTABLE,
        reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
    )
    service.submit_job(spec, "submit-checkpointable")

    def execute(_payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        raise SystemExit("simulated process loss during training")

    journal_path = tmp_path / "worker.db"
    worker = WorkerRuntime(
        node_id="worker", journal_path=journal_path, transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    with pytest.raises(SystemExit):
        worker.run_once("claim-training")
    restarted = WorkerRuntime(
        node_id="worker", journal_path=journal_path, transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    assert restarted.recover_incomplete() is None
    assert service.repository.job(spec.job_id)["state"] in {"acknowledged", "running"}


def test_artifact_upload_resumes_after_restart_and_is_scoped_to_each_job(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")

    class InterruptedUpload(ServiceTransport):
        interrupt = True

        def put_artifact_chunk(self, **kwargs: Any) -> dict[str, Any]:
            if self.interrupt:
                self.interrupt = False
                raise ConnectionError("simulated lost connection during upload")
            return super().put_artifact_chunk(**kwargs)

    transport = InterruptedUpload(service, "worker", token)
    journal_path = tmp_path / "worker.db"

    def execute(payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        output = Path(payload["output_dir"])
        output.mkdir(parents=True)
        (output / "result.txt").write_text("same result", encoding="utf-8")
        return {"output_dir": str(output)}

    def new_worker() -> WorkerRuntime:
        return WorkerRuntime(
            node_id="worker", journal_path=journal_path, transport=transport,
            executors={"output-job": execute}, secret_protector=TestProtector(),
        )

    def submit(key: str) -> JobSpec:
        spec = JobSpec(kind="output-job", payload={
            "output_mounts": ["output_dir"],
            "collect_outputs": [{"result_key": "output_dir", "kind": "result"}],
        })
        service.submit_job(spec, key)
        return spec

    first = submit("submit-first")
    with pytest.raises(ConnectionError):
        new_worker().run_once("claim-first")
    assert service.repository.job(first.job_id)["state"] in {"acknowledged", "running"}
    assert new_worker().sync_all_pending() >= 1
    assert service.repository.job(first.job_id)["state"] == "succeeded"

    second = submit("submit-second")
    assert new_worker().run_once("claim-second") == "succeeded"
    assert service.repository.job(second.job_id)["state"] == "succeeded"
    first_result = json.loads(service.repository.job(first.job_id)["result_json"])
    second_result = json.loads(service.repository.job(second.job_id)["result_json"])
    assert first_result["artifacts"][0]["sha256"] == second_result["artifacts"][0]["sha256"]
    assert first_result["artifacts"][0]["artifact_id"] != second_result["artifacts"][0]["artifact_id"]


def test_accepted_completion_is_replayed_after_response_loss(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    spec = JobSpec(kind="quick-job", payload={})
    service.submit_job(spec, "submit-quick")

    class LostCompletion(ServiceTransport):
        interrupted = False

        def complete(
            self, lease: dict[str, Any], message: dict[str, Any], *, idempotency_key: str,
        ) -> dict[str, Any]:
            result = super().complete(lease, message, idempotency_key=idempotency_key)
            if not self.interrupted:
                self.interrupted = True
                raise ConnectionError("simulated lost completion response")
            return result

    transport = LostCompletion(service, "worker", token)
    journal_path = tmp_path / "worker.db"

    def new_worker() -> WorkerRuntime:
        return WorkerRuntime(
            node_id="worker", journal_path=journal_path, transport=transport,
            executors={spec.kind: lambda _payload, _progress: {"result": "done"}},
            secret_protector=TestProtector(),
        )

    with pytest.raises(ConnectionError):
        new_worker().run_once("claim-quick")
    assert service.repository.job(spec.job_id)["state"] == "succeeded"
    assert new_worker().sync_all_pending() == 1
    assert new_worker().journal.job(spec.job_id)["sync_state"] == "synced"


def test_replayed_claim_does_not_repeat_a_completed_job(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    _, transport = registered(service, "worker")
    spec = JobSpec(kind="counted-job", payload={})
    service.submit_job(spec, "submit-counted")
    executions = 0

    def execute(_payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        nonlocal executions
        executions += 1
        return {"count": executions}

    worker = WorkerRuntime(
        node_id="worker", journal_path=tmp_path / "worker.db", transport=transport,
        executors={spec.kind: execute}, secret_protector=TestProtector(),
    )
    assert worker.run_once("same-claim-key") == "succeeded"
    assert worker.run_once("same-claim-key") == "succeeded"
    assert executions == 1
    assert service.repository.job(spec.job_id)["state"] == "succeeded"


def test_stale_progress_after_reassignment_is_retained_without_stopping_worker(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    spec = JobSpec(kind="pure", payload={})
    service.submit_job(spec, "submit-stale-progress")
    lease = service.claim_job(node_id="worker", token=token, idempotency_key="claim-stale")
    assert lease is not None
    journal_path = tmp_path / "worker.db"
    journal = WorkerJournal(journal_path, TestProtector())
    journal.accept_lease(lease)
    journal.record_progress(spec.job_id, {"step": 1})
    service.repository.expire_leases(datetime.now(UTC) + timedelta(hours=1))
    service.repository.reconcile_orphan(spec.job_id, "requeue")

    class FencedTransport(ServiceTransport):
        def progress(
            self, lease: dict[str, Any], message: dict[str, Any], *, idempotency_key: str,
        ) -> dict[str, Any]:
            raise CoordinatorTransportError("old lease", transient=False, status=409)

        def renew(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
            raise CoordinatorTransportError("old lease", transient=False, status=409)

    worker = WorkerRuntime(
        node_id="worker", journal_path=journal_path,
        transport=FencedTransport(service, "worker", token),
        executors={}, secret_protector=TestProtector(),
    )
    assert worker.sync_all_pending() == 0
    assert worker.journal.job(spec.job_id)["local_state"] == "stale_attempt"
    assert worker.journal.pending_messages() == []
    assert service.repository.job(spec.job_id)["state"] == "ready"


def test_progress_conflict_on_live_lease_remains_actionable(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token, _ = registered(service, "worker")
    spec = JobSpec(kind="pure", payload={})
    service.submit_job(spec, "submit-conflict")
    lease = service.claim_job(node_id="worker", token=token, idempotency_key="claim-conflict")
    assert lease is not None
    journal_path = tmp_path / "worker.db"
    journal = WorkerJournal(journal_path, TestProtector())
    journal.accept_lease(lease)
    journal.record_progress(spec.job_id, {"step": 1})

    class ConflictingProgress(ServiceTransport):
        def progress(
            self, lease: dict[str, Any], message: dict[str, Any], *, idempotency_key: str,
        ) -> dict[str, Any]:
            raise CoordinatorTransportError("conflicting progress", transient=False, status=409)

    worker = WorkerRuntime(
        node_id="worker", journal_path=journal_path,
        transport=ConflictingProgress(service, "worker", token),
        executors={}, secret_protector=TestProtector(),
    )
    with pytest.raises(CoordinatorTransportError, match="conflicting progress"):
        worker.sync_all_pending()
    assert worker.journal.job(spec.job_id)["local_state"] == "accepted"
    assert len(worker.journal.pending_messages()) == 1


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


def test_worker_records_rejected_stale_completion_without_retrying(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    token_a, _ = registered(service, "a")
    token_b, _ = registered(service, "b")
    spec = JobSpec(kind="pure", payload={})
    service.submit_job(spec, "submit")

    def execute(_payload: dict[str, Any], _progress: Any) -> dict[str, Any]:
        service.repository.expire_leases(datetime.now(UTC) + timedelta(hours=1))
        service.repository.reconcile_orphan(spec.job_id, "requeue")
        service.claim_job(node_id="b", token=token_b, idempotency_key="claim-b")
        return {"from": "old"}

    worker = WorkerRuntime(
        node_id="a", journal_path=tmp_path / "worker.db",
        transport=ServiceTransport(service, "a", token_a),
        executors={"pure": execute}, secret_protector=TestProtector(),
    )
    assert worker.run_once("claim-a") == "stale_attempt"
    assert worker.journal.job(spec.job_id)["local_state"] == "stale_attempt"
    assert worker.journal.pending_messages() == []
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


def test_overview_uses_recorded_dependencies_and_heartbeat_age(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    service.record_product_item(
        record_id="broker-check", category="experiment", title="Broker",
        status="CAPABILITIES_SATISFIED", artifact_sha256="a" * 64,
        summary={"phase": "retrieval"},
    )
    service.record_product_item(
        record_id="snapshot", category="snapshot", title="Vault",
        status="COMPLETE", artifact_sha256="b" * 64, summary={},
    )
    assert service.overview()["external_dependencies"] == {
        "ai_broker": "verified", "vault": "verified", "model_drift": "unknown",
    }
    pairing = service.create_pairing_code()
    service.pair_and_register(pairing_code=pairing, node_id="stale-node", hostname="old-worker")
    with service.repository.transaction() as db:
        db.execute("UPDATE nodes SET last_heartbeat_at='2020-01-01T00:00:00Z' WHERE node_id='stale-node'")
    assert service.overview()["nodes"][0]["status"] == "offline"


def test_revoked_worker_cannot_heartbeat_or_download(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / "coordinator.db")
    registered = service.pair_and_register(
        pairing_code=service.create_pairing_code(), node_id="revoked-node", hostname="worker"
    )
    client = TestClient(create_app(service, app_token="desktop-secret"))
    route = "/app/v1/nodes/revoked-node/revoke"
    assert client.post(route).status_code == 401
    assert client.post(route, headers={"X-App-Token": "desktop-secret"}).json()["status"] == "revoked"
    assert service.overview()["nodes"][0]["status"] == "revoked"
    with pytest.raises(PermissionError):
        service.heartbeat(node_id="revoked-node", token=registered["device_token"], capabilities=None)
    with pytest.raises(PermissionError):
        service.artifact_download(node_id="revoked-node", token=registered["device_token"], sha256="a" * 64)


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
