"""Emparejamiento, registro y latidos de los nodos worker.

El codigo de emparejamiento caduca y se consume una sola vez: es la
unica ventana en la que un nodo desconocido puede entrar.
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from local_ai_lab.capabilities.environment import merge_capability_report
from local_ai_lab.domain.common import canonical_json, sha256_text, utc_timestamp
from local_ai_lab.coordinator.repository.base import (
    CoordinatorConflict,
)
from local_ai_lab.coordinator.repository.base import RepositorioBase


class NodosMixin(RepositorioBase):
    """Emparejamiento, registro y latidos de los nodos worker."""

    def create_pairing_code(self, valid_seconds: int = 300) -> str:
        if valid_seconds < 30 or valid_seconds > 900:
            raise ValueError("pairing code lifetime must be between 30 and 900 seconds")
        code = f"{secrets.randbelow(100_000_000):08d}"
        expires = datetime.now(UTC) + timedelta(seconds=valid_seconds)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO pairing_codes(code_hash, expires_at) VALUES (?, ?)",
                (sha256_text(code), expires.isoformat().replace("+00:00", "Z")),
            )
        return code

    def consume_pairing_code(self, code: str) -> str:
        now = datetime.now(UTC)
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM pairing_codes WHERE code_hash=?", (sha256_text(code),)
            ).fetchone()
            if row is None or row["used_at"] is not None:
                raise CoordinatorConflict("pairing code is invalid or already used")
            expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            if expires <= now:
                raise CoordinatorConflict("pairing code has expired")
            db.execute(
                "UPDATE pairing_codes SET used_at=? WHERE code_hash=?",
                (now.isoformat().replace("+00:00", "Z"), row["code_hash"]),
            )
        return secrets.token_urlsafe(32)

    def register_node(
        self,
        *,
        node_id: str,
        hostname: str,
        protocol_min: int,
        protocol_max: int,
        auth_token: str,
    ) -> dict[str, Any]:
        if protocol_min > 1 or protocol_max < 1:
            raise CoordinatorConflict("worker and coordinator have no common protocol version")
        now = utc_timestamp()
        with self.transaction() as db:
            db.execute(
                """
                INSERT INTO nodes(node_id, hostname, protocol_min, protocol_max,
                                  auth_token_hash, status, registered_at, last_heartbeat_at)
                VALUES (?, ?, ?, ?, ?, 'online', ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    hostname=excluded.hostname,
                    protocol_min=excluded.protocol_min,
                    protocol_max=excluded.protocol_max,
                    auth_token_hash=excluded.auth_token_hash,
                    capabilities_json=NULL,
                    environment_generation=nodes.environment_generation + 1,
                    status='online',
                    last_heartbeat_at=excluded.last_heartbeat_at
                """,
                (node_id, hostname, protocol_min, protocol_max, sha256_text(auth_token), now, now),
            )
            generation = db.execute(
                "SELECT environment_generation FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()["environment_generation"]
            self._invalidate_preflights(db, node_id, generation)
        return {"node_id": node_id, "protocol_version": 1, "registered_at": now}

    def authenticate_node(self, node_id: str, token: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT auth_token_hash, status FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
        return bool(row and row["status"] != "revoked" and secrets.compare_digest(row["auth_token_hash"], sha256_text(token)))

    def heartbeat(self, node_id: str, capabilities: dict[str, Any] | None) -> dict[str, Any]:
        now = utc_timestamp()
        with self.transaction() as db:
            current = db.execute(
                "SELECT capabilities_json, environment_generation FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if current is None:
                raise CoordinatorConflict("node is not registered")
            generation = current["environment_generation"]
            encoded_capabilities: str | None = None
            if capabilities is not None:
                existing = (
                    json.loads(current["capabilities_json"])
                    if current["capabilities_json"] else {}
                )
                merged, changed_keys = merge_capability_report(
                    existing, capabilities, generation=generation, now=now,
                )
                generation += bool(changed_keys)
                encoded_capabilities = canonical_json(merged)
            changed = db.execute(
                """UPDATE nodes SET status='online', last_heartbeat_at=?,
                   capabilities_json=COALESCE(?, capabilities_json), environment_generation=?
                   WHERE node_id=? AND status!='revoked'""",
                (now, encoded_capabilities, generation, node_id),
            ).rowcount
            if not changed:
                raise CoordinatorConflict("node is not registered")
            self._invalidate_preflights(db, node_id, generation)
        return {"coordinator_time": now, "next_heartbeat_seconds": 15}

    def revoke_node(self, node_id: str) -> None:
        with self.transaction() as db:
            if not db.execute("UPDATE nodes SET status='revoked' WHERE node_id=?", (node_id,)).rowcount:
                raise KeyError(node_id)

    def active_artifact_job(self, node_id: str, *, sha256: str | None = None) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM jobs WHERE assigned_node_id=? AND state IN
                   ('leased', 'acknowledged', 'running', 'pausing', 'paused', 'cancelling')
                   AND lease_expires_at > ?""",
                (node_id, utc_timestamp()),
            ).fetchall()
        matches = []
        for row in rows:
            payload = json.loads(row["spec_json"])["payload"]
            if sha256 is None:
                if payload.get("collect_outputs"):
                    matches.append(dict(row))
            elif any(item.get("sha256") == sha256 for item in payload.get("input_artifacts", [])):
                matches.append(dict(row))
        if len(matches) != 1:
            raise CoordinatorConflict("artifact is not authorized for exactly one active node job")
        return matches[0]

    def bind_artifact_upload(self, *, artifact_id: str, node_id: str, job: dict[str, Any], sha256: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO artifact_upload_owners VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, node_id, job["job_id"], job["attempt_id"],
                 job["lease_generation"], sha256, utc_timestamp()),
            )

    def authorize_artifact_upload(self, *, artifact_id: str, node_id: str,
                                  job_id: str | None = None, sha256: str | None = None) -> None:
        self.require_upload_not_retired(artifact_id)
        with self.connect() as db:
            owner = db.execute(
                "SELECT * FROM artifact_upload_owners WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            job = db.execute("SELECT * FROM jobs WHERE job_id=?", (owner["job_id"],)).fetchone() if owner else None
        if (
            owner is None or job is None or owner["node_id"] != node_id
            or (job_id is not None and owner["job_id"] != job_id)
            or (sha256 is not None and owner["sha256"] != sha256)
            or job["attempt_id"] != owner["attempt_id"]
            or job["lease_generation"] != owner["lease_generation"]
            or not job["lease_expires_at"] or job["lease_expires_at"] <= utc_timestamp()
            or job["state"] not in {"leased", "acknowledged", "running", "pausing", "paused", "cancelling"}
        ):
            raise CoordinatorConflict("artifact upload is not authorized for this active attempt")

    def require_upload_not_retired(self, artifact_id: str) -> None:
        with self.connect() as db:
            retired = db.execute(
                "SELECT 1 FROM retired_artifact_uploads WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
        if retired:
            raise CoordinatorConflict("artifact upload was retired by an approved storage cleanup")
