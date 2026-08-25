from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

from local_ai_lab.security.secrets import SecretProtector, platform_secret_protector
from local_ai_lab.worker.journal import WorkerJournal


class CoordinatorTransport(Protocol):
    def claim(self, *, idempotency_key: str) -> dict[str, Any] | None: ...
    def ack(self, lease: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]: ...
    def progress(self, lease: dict[str, Any], message: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]: ...
    def complete(self, lease: dict[str, Any], message: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]: ...


class WorkerJobCancelled(RuntimeError):
    pass


class WorkerRuntime:
    """Executes persisted jobs and keeps an outbox while disconnected."""

    def __init__(
        self,
        *,
        node_id: str,
        journal_path: Path,
        transport: CoordinatorTransport,
        executors: dict[str, Callable[[dict[str, Any], Callable[[dict[str, Any]], None]], dict[str, Any]]],
        secret_protector: SecretProtector | None = None,
    ) -> None:
        self.node_id = node_id
        self.journal = WorkerJournal(journal_path, secret_protector or platform_secret_protector())
        self.transport = transport
        self.executors = executors

    def run_once(self, claim_key: str) -> str | None:
        lease = self.transport.claim(idempotency_key=claim_key)
        if lease is None:
            return None
        self.journal.accept_lease(lease)
        self.transport.ack(lease, idempotency_key=f"ack:{lease['job_id']}:{lease['attempt_id']}")
        self.journal.mark_acknowledged(lease["job_id"])
        self.journal.mark_running(lease["job_id"])
        kind = lease["spec"]["kind"]
        executor = self.executors.get(kind)
        if executor is None:
            message = self.journal.finish(
                lease["job_id"], "failed", {"code": "UNSUPPORTED_JOB_KIND", "kind": kind}
            )
        else:
            try:
                self._raise_if_cancelled(lease)
                payload = self._materialize_payload(lease)
                result = executor(
                    payload,
                    lambda progress: self._record_and_sync_progress(lease, progress),
                )
                result = self._package_result_outputs(lease, payload, result)
            except WorkerJobCancelled:
                message = self.journal.finish(
                    lease["job_id"], "cancelled", {"code": "CANCELLED_BY_COORDINATOR"}
                )
            except Exception as error:
                message = self.journal.finish(
                    lease["job_id"],
                    "failed",
                    {"code": "EXECUTOR_FAILED", "type": type(error).__name__},
                )
            else:
                message = self.journal.finish(lease["job_id"], "succeeded", result)
        self.sync_pending(lease)
        return message["outcome"]

    def _record_and_sync_progress(self, lease: dict[str, Any], payload: dict[str, Any]) -> None:
        self.journal.record_progress(lease["job_id"], payload)
        try:
            renew = getattr(self.transport, "renew", None)
            if renew is not None:
                sequence = self.journal.job(lease["job_id"])["progress_sequence"]
                renew(lease, idempotency_key=f"renew:{lease['job_id']}:{sequence}")
            self.sync_pending(lease)
            self._raise_if_cancelled(lease)
        except WorkerJobCancelled:
            raise
        except Exception:
            # The journal/outbox is authoritative while the Coordinator is unreachable.
            return

    def _raise_if_cancelled(self, lease: dict[str, Any]) -> None:
        control = getattr(self.transport, "control", None)
        if control is None:
            return
        response = control(
            lease, idempotency_key=f"control:{lease['job_id']}:{lease['lease_generation']}"
        )
        if response.get("action") == "cancel":
            raise WorkerJobCancelled(lease["job_id"])

    def sync_pending(self, lease: dict[str, Any]) -> int:
        delivered = 0
        for message in self.journal.pending_messages():
            if message["job_id"] != lease["job_id"]:
                continue
            if message["kind"] == "progress":
                self.transport.progress(
                    lease, message["payload"], idempotency_key=message["idempotency_key"]
                )
            elif message["kind"] == "complete":
                message = self._resolve_completion_artifacts(message)
                self.transport.complete(
                    lease, message["payload"], idempotency_key=message["idempotency_key"]
                )
            else:
                continue
            self.journal.mark_delivered(message["message_id"])
            delivered += 1
        return delivered

    def _materialize_payload(self, lease: dict[str, Any]) -> dict[str, Any]:
        payload = dict(lease["spec"]["payload"])
        cache_root = self.journal.path.parent / "cache"
        for descriptor in payload.get("input_artifacts", []):
            if not isinstance(descriptor, dict):
                raise ValueError("input artifact descriptor must be an object")
            digest = descriptor.get("sha256")
            mount_as = descriptor.get("mount_as")
            if not isinstance(digest, str) or not isinstance(mount_as, str) or not mount_as.isidentifier():
                raise ValueError("input artifact requires SHA-256 and a safe mount key")
            blob = cache_root / "sha256" / digest[:2] / digest
            if not blob.is_file() or _hash_file(blob) != digest:
                download = getattr(self.transport, "download_artifact", None)
                if download is None:
                    raise RuntimeError("worker transport cannot download input artifacts")
                content = download(digest)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError("input artifact hash mismatch")
                blob.parent.mkdir(parents=True, exist_ok=True)
                temporary = blob.with_name(blob.name + f".{uuid.uuid4().hex}.tmp")
                temporary.write_bytes(content)
                temporary.replace(blob)
            if descriptor.get("archive") == "zip":
                mounted = cache_root / "expanded" / digest
                if not mounted.is_dir():
                    safe_extract_zip(blob, mounted)
                payload[mount_as] = str(mounted)
            else:
                payload[mount_as] = str(blob)
        output_parent = self.journal.path.parent / "outputs" / lease["job_id"]
        for mount_as in payload.get("output_mounts", []):
            if not isinstance(mount_as, str) or not mount_as.isidentifier():
                raise ValueError("output mount key is invalid")
            output_parent.mkdir(parents=True, exist_ok=True)
            payload[mount_as] = str(output_parent / mount_as)
        return payload

    def _package_result_outputs(
        self, lease: dict[str, Any], payload: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        sanitized = dict(result)
        local_artifacts: list[dict[str, Any]] = []
        outgoing = self.journal.path.parent / "outgoing" / lease["job_id"]
        for descriptor in payload.get("collect_outputs", []):
            result_key = descriptor.get("result_key")
            kind = descriptor.get("kind")
            if not isinstance(result_key, str) or not isinstance(kind, str):
                raise ValueError("output collection descriptor is invalid")
            source = Path(str(result[result_key])).resolve(strict=True)
            if source.is_dir():
                archive, digest = deterministic_zip(source, outgoing / f"{kind}.zip")
                media_type = "application/zip"
            elif source.is_file():
                archive, digest = source, _hash_file(source)
                media_type = "application/octet-stream"
            else:
                raise ValueError("collected output is not a regular file or directory")
            sanitized.pop(result_key, None)
            local_artifacts.append(
                {
                    "kind": kind, "local_path": str(archive), "sha256": digest,
                    "size": archive.stat().st_size, "media_type": media_type,
                }
            )
        if local_artifacts:
            sanitized["_local_artifacts"] = local_artifacts
        return sanitized

    def _resolve_completion_artifacts(self, message: dict[str, Any]) -> dict[str, Any]:
        outer = dict(message["payload"])
        result = dict(outer.get("payload", {}))
        local = result.pop("_local_artifacts", [])
        if not local:
            return message
        uploaded = [self._upload_artifact(item) for item in local]
        result["artifacts"] = uploaded
        outer["payload"] = result
        self.journal.replace_outbox_payload(message["message_id"], outer)
        return {**message, "payload": outer}

    def _upload_artifact(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        path = Path(descriptor["local_path"]).resolve(strict=True)
        digest = descriptor["sha256"]
        if _hash_file(path) != digest:
            raise ValueError("prepared result artifact hash mismatch")
        initiate = getattr(self.transport, "initiate_artifact")
        put_chunk = getattr(self.transport, "put_artifact_chunk")
        commit = getattr(self.transport, "commit_artifact")
        chunk_size = 4 * 1024 * 1024
        upload = initiate(
            expected_sha256=digest, expected_size=path.stat().st_size,
            chunk_size=chunk_size, idempotency_key=f"artifact:{digest}:init",
        )
        with path.open("rb") as stream:
            index = 0
            while content := stream.read(chunk_size):
                put_chunk(
                    artifact_id=upload["artifact_id"], index=index, content=content,
                    chunk_sha256=hashlib.sha256(content).hexdigest(),
                    idempotency_key=f"artifact:{digest}:chunk:{index}",
                )
                index += 1
        committed = commit(
            artifact_id=upload["artifact_id"], idempotency_key=f"artifact:{digest}:commit"
        )
        return {
            "kind": descriptor["kind"], "sha256": committed["sha256"],
            "size": descriptor["size"], "media_type": descriptor["media_type"],
            "artifact_id": upload["artifact_id"],
        }

    def resume_sync(self, job_id: str) -> int:
        return self.sync_pending(self.journal.lease(job_id))

    def sync_all_pending(self) -> int:
        delivered = 0
        for job_id in self.journal.pending_job_ids():
            delivered += self.resume_sync(job_id)
        return delivered


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()
from local_ai_lab.artifacts.archive import deterministic_zip, safe_extract_zip
