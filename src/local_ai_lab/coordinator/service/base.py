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

    def _authenticate(self, node_id: str, token: str) -> None:
        if not self.repository.authenticate_node(node_id, token):
            raise AuthenticationError("node credentials are invalid")

    def _idempotent(
        self,
        *,
        scope: str,
        key: str,
        request: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        if not key or len(key) > 200:
            raise ValueError("a bounded Idempotency-Key is required")
        request_hash = sha256_text(canonical_json(request))
        with self._idempotency_lock:
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
