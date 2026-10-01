"""Estado del servicio, autenticacion de nodos e idempotencia.

La idempotencia se resuelve aqui y en un solo sitio: cada caso de uso que
escribe pasa por `_idempotent`, de modo que repetir una peticion con la
misma clave devuelve la respuesta anterior en vez de duplicar trabajo.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from local_ai_lab.artifacts.store import ArtifactStore
from local_ai_lab.coordinator.repository import CoordinatorConflict, CoordinatorRepository
from local_ai_lab.domain.common import canonical_json, sha256_text, utc_timestamp
from local_ai_lab.domain.jobs import LeaseGrant
from local_ai_lab.feedback.repository import FeedbackRepository


class AuthenticationError(PermissionError):
    pass


class IdempotencyConflict(CoordinatorConflict):
    pass


class ServicioBase:
    protocol_version = 1

    def __init__(self, database_path: Path) -> None:
        self.repository = CoordinatorRepository(database_path)
        self.feedback = FeedbackRepository(database_path)
        self.artifacts = ArtifactStore(database_path.parent / "artifacts")
        self._idempotency_lock = threading.RLock()

    def storage_cleanup_plan(self, older_than_days: int = 30) -> dict[str, Any]:
        from local_ai_lab.maintenance.retention import create_cleanup_plan
        with self._idempotency_lock:
            return create_cleanup_plan(self.artifacts, self.repository, older_than_days)

    def apply_storage_cleanup(self, plan_id: str) -> dict[str, Any]:
        from local_ai_lab.maintenance.retention import apply_cleanup_plan
        with self._idempotency_lock:
            return apply_cleanup_plan(self.artifacts, self.repository, plan_id)

    def pending_storage_cleanup(self) -> dict[str, Any] | None:
        from local_ai_lab.maintenance.retention import pending_cleanup_plan
        return pending_cleanup_plan(self.repository)

    def _authenticate(self, node_id: str, token: str) -> None:
        if not self.repository.authenticate_node(node_id, token):
            raise AuthenticationError("node credentials are invalid")

    def _recover_expired_jobs(self) -> None:
        self.repository.expire_leases()
        # A previous process may have stopped after marking ORPHANED but
        # before applying the policy decision.
        for job_id in self.repository.orphaned_jobs():
            job = self.repository.job(job_id)
            if job is None:
                continue
            spec = json.loads(job["spec_json"])
            automatic = (
                spec.get("idempotency_class") == "pure"
                and spec.get("reassignment_policy") == "automatic"
                and job["control_action"] != "cancel"
            )
            try:
                self.repository.reconcile_orphan(
                    job_id, "requeue" if automatic else "needs_review"
                )
            except CoordinatorConflict:
                # Another Coordinator request may already have reconciled this job.
                continue

    def _idempotent(
        self,
        *,
        scope: str,
        key: str,
        request: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
        authorization: Callable[[], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        if not key or len(key) > 200:
            raise ValueError("a bounded Idempotency-Key is required")
        request_hash = sha256_text(canonical_json(request))
        with self._idempotency_lock:
            # Replayed receipts need authorization too. An explicit rejection must
            # not reserve the legitimate caller's key or enter the response cache.
            if authorization is not None:
                rejected = authorization()
                if rejected is not None:
                    return rejected
            with self.repository.transaction() as db:
                existing = db.execute(
                    "SELECT request_hash, response_json FROM idempotency WHERE scope=? AND idempotency_key=?",
                    (scope, key),
                ).fetchone()
                if existing:
                    if existing["request_hash"] != request_hash:
                        raise IdempotencyConflict("idempotency key was reused with another request")
                    return json.loads(existing["response_json"])

            response = operation()
            with self.repository.transaction() as db:
                db.execute(
                    "INSERT INTO idempotency VALUES (?, ?, ?, ?, ?)",
                    (scope, key, request_hash, canonical_json(response), utc_timestamp()),
                )
        return response

def _lease_payload(grant: LeaseGrant) -> dict[str, Any]:
    payload = asdict(grant)
    return payload
