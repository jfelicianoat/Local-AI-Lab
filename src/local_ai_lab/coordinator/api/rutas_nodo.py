"""Rutas del protocolo Coordinator/Worker (`/node/v1`).

Aqui no vale el token de escritorio: cada nodo se autentica con su propia
credencial, emitida al emparejarse.
"""
from __future__ import annotations

import base64
import binascii
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from local_ai_lab.coordinator.service import (
    CoordinatorService,
)
from local_ai_lab.coordinator.api.auxiliares import _call, _node_credentials
from local_ai_lab.coordinator.api.modelos import (
    ArtifactChunkRequest,
    ArtifactInitiateRequest,
    ClaimRequest,
    CompleteRequest,
    HeartbeatRequest,
    LeaseMutation,
    PairRequest,
    ProgressRequest,
    RenewRequest,
)


def registrar_rutas_nodo(app: FastAPI, service: CoordinatorService) -> None:
    """Cuelga en `app` las rutas que consumen los nodos worker."""

    @app.post("/node/v1/pair")
    def pair(body: PairRequest) -> dict[str, Any]:
        return _call(
            service.pair_and_register,
            pairing_code=body.pairing_code,
            node_id=body.node_id,
            hostname=body.hostname,
            protocol_min=body.protocol_min,
            protocol_max=body.protocol_max,
        )

    @app.post("/node/v1/heartbeats")
    def heartbeat(
        body: HeartbeatRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.heartbeat, node_id=node_id, token=token, capabilities=body.capabilities
        )

    @app.post("/node/v1/artifacts/initiate")
    def initiate_artifact(
        body: ArtifactInitiateRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.initiate_artifact_upload, node_id=node_id, token=token,
            expected_sha256=body.expected_sha256, expected_size=body.expected_size,
            chunk_size=body.chunk_size, idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/artifacts/{artifact_id}/chunks/{index}")
    def put_artifact_chunk(
        artifact_id: str,
        index: int,
        body: ArtifactChunkRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(422, "content_base64 is invalid") from error
        return _call(
            service.put_artifact_chunk, node_id=node_id, token=token,
            artifact_id=artifact_id, index=index, content=content,
            chunk_sha256=body.chunk_sha256, idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/artifacts/{artifact_id}/commit")
    def commit_artifact(
        artifact_id: str,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.commit_artifact_upload, node_id=node_id, token=token,
            artifact_id=artifact_id, idempotency_key=idempotency_key,
        )

    @app.get("/node/v1/artifacts/sha256/{sha256}", response_class=FileResponse)
    def download_artifact(
        sha256: str,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
    ) -> FileResponse:
        node_id, token = credentials
        path = _call(service.artifact_download, node_id=node_id, token=token, sha256=sha256)
        return FileResponse(
            path, media_type="application/octet-stream", filename=f"sha256-{sha256}.blob"
        )

    @app.post("/node/v1/jobs/claim")
    def claim(
        body: ClaimRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return {
            "lease": _call(
                service.claim_job,
                node_id=node_id,
                token=token,
                idempotency_key=idempotency_key,
                lease_seconds=body.lease_seconds,
            )
        }

    @app.post("/node/v1/jobs/{job_id}/ack")
    def ack(
        job_id: str,
        body: LeaseMutation,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.ack_job,
            node_id=node_id,
            token=token,
            job_id=job_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/lease/renew")
    def renew(
        job_id: str,
        body: RenewRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.renew_lease,
            node_id=node_id,
            token=token,
            job_id=job_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            lease_seconds=body.lease_seconds,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/progress")
    def progress(
        job_id: str,
        body: ProgressRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.progress,
            node_id=node_id,
            token=token,
            job_id=job_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            sequence=body.sequence,
            payload=body.payload,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/control")
    def job_control(
        job_id: str,
        body: LeaseMutation,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        return _call(
            service.job_control,
            node_id=node_id, token=token, job_id=job_id,
            lease_token=body.lease_token, lease_generation=body.lease_generation,
            idempotency_key=idempotency_key,
        )

    @app.post("/node/v1/jobs/{job_id}/complete")
    def complete(
        job_id: str,
        body: CompleteRequest,
        credentials: Annotated[tuple[str, str], Depends(_node_credentials)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        node_id, token = credentials
        if body.outcome not in ("succeeded", "failed", "cancelled"):
            raise HTTPException(422, "outcome must be succeeded, failed, or cancelled")
        return _call(
            service.complete_job,
            node_id=node_id,
            token=token,
            job_id=job_id,
            attempt_id=body.attempt_id,
            lease_token=body.lease_token,
            lease_generation=body.lease_generation,
            outcome=body.outcome,
            payload=body.payload,
            idempotency_key=idempotency_key,
        )
