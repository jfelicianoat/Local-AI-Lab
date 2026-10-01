"""Emparejamiento de nodos, latidos y transferencia de artefactos.

Los artefactos viajan por trozos y se verifican por SHA-256 al bajar: un
artefacto a medias no puede pasar por bueno.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from local_ai_lab.coordinator.service.entrenamiento import EntrenamientoMixin


class NodosMixin(EntrenamientoMixin):
    """Emparejamiento de nodos, latidos y transferencia de artefactos."""

    def revoke_node(self, node_id: str) -> dict[str, str]:
        self.repository.revoke_node(node_id)
        return {"node_id": node_id, "status": "revoked"}

    def pair_and_register(
        self,
        *,
        pairing_code: str,
        node_id: str,
        hostname: str,
        protocol_min: int = 1,
        protocol_max: int = 1,
    ) -> dict[str, Any]:
        token = self.repository.consume_pairing_code(pairing_code)
        registration = self.repository.register_node(
            node_id=node_id,
            hostname=hostname,
            protocol_min=protocol_min,
            protocol_max=protocol_max,
            auth_token=token,
        )
        return {**registration, "device_token": token}

    def heartbeat(
        self, *, node_id: str, token: str, capabilities: dict[str, Any] | None
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        return self.repository.heartbeat(node_id, capabilities)

    def initiate_artifact_upload(
        self, *, node_id: str, token: str, expected_sha256: str,
        expected_size: int, chunk_size: int, idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        job = self.repository.active_artifact_job(node_id)
        def initiate() -> dict[str, Any]:
            result = asdict(self.artifacts.initiate(
                expected_sha256=expected_sha256, expected_size=expected_size,
                chunk_size=chunk_size,
            ))
            self.repository.bind_artifact_upload(
                artifact_id=result["artifact_id"], node_id=node_id,
                job=job, sha256=expected_sha256,
            )
            return result
        response = self._idempotent(
            scope=f"node:{node_id}:artifact:initiate", key=idempotency_key,
            request={
                "expected_sha256": expected_sha256, "expected_size": expected_size,
                "chunk_size": chunk_size,
            },
            operation=initiate,
        )
        self.repository.require_upload_not_retired(response["artifact_id"])
        return response

    def put_artifact_chunk(
        self, *, node_id: str, token: str, artifact_id: str, index: int,
        content: bytes, chunk_sha256: str, idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        self.repository.authorize_artifact_upload(artifact_id=artifact_id, node_id=node_id)
        return self._idempotent(
            scope=f"artifact:{artifact_id}:chunk:{index}", key=idempotency_key,
            request={"index": index, "chunk_sha256": chunk_sha256, "size": len(content)},
            operation=lambda: self.artifacts.put_chunk(
                artifact_id=artifact_id, index=index, content=content,
                chunk_sha256=chunk_sha256,
            ),
        )

    def commit_artifact_upload(
        self, *, node_id: str, token: str, artifact_id: str, idempotency_key: str,
    ) -> dict[str, Any]:
        self._authenticate(node_id, token)
        self.repository.authorize_artifact_upload(artifact_id=artifact_id, node_id=node_id)
        return self._idempotent(
            scope=f"artifact:{artifact_id}:commit", key=idempotency_key,
            request={"artifact_id": artifact_id},
            operation=lambda: self.artifacts.commit(artifact_id),
        )

    def artifact_download(self, *, node_id: str, token: str, sha256: str) -> Path:
        self._authenticate(node_id, token)
        self.repository.active_artifact_job(node_id, sha256=sha256)
        if not self.artifacts.verify(sha256):
            raise KeyError(f"unknown or corrupt artifact: {sha256}")
        return self.artifacts.blob_path(sha256)
