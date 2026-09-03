"""Emparejamiento, registro y latidos de los nodos worker.

El codigo de emparejamiento caduca y se consume una sola vez: es la
unica ventana en la que un nodo desconocido puede entrar.
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from local_ai_lab.domain.common import canonical_json, sha256_text, utc_timestamp
from local_ai_lab.coordinator.repository.base import (
    _EVIDENCE_RANK,
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
                    status='online',
                    last_heartbeat_at=excluded.last_heartbeat_at
                """,
                (node_id, hostname, protocol_min, protocol_max, sha256_text(auth_token), now, now),
            )
        return {"node_id": node_id, "protocol_version": 1, "registered_at": now}

    def authenticate_node(self, node_id: str, token: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT auth_token_hash FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
        return bool(row and secrets.compare_digest(row["auth_token_hash"], sha256_text(token)))

    def heartbeat(self, node_id: str, capabilities: dict[str, Any] | None) -> dict[str, Any]:
        now = utc_timestamp()
        with self.transaction() as db:
            encoded_capabilities: str | None = None
            if capabilities is not None:
                current = db.execute(
                    "SELECT capabilities_json FROM nodes WHERE node_id=?", (node_id,)
                ).fetchone()
                if current is None:
                    raise CoordinatorConflict("node is not registered")
                merged = dict(capabilities)
                existing = (
                    json.loads(current["capabilities_json"])
                    if current["capabilities_json"] else {}
                )
                workload_rank = {"untested": 0, "tested": 1, "benchmarked": 2}
                workloads: dict[str, dict[str, Any]] = {}
                for item in [
                    *existing.get("workloads", []),
                    *merged.get("workloads", []),
                ]:
                    if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
                        continue
                    previous = workloads.get(item["kind"])
                    if previous is None or workload_rank.get(item.get("status"), -1) >= workload_rank.get(
                        previous.get("status"), -1
                    ):
                        workloads[item["kind"]] = item
                merged["workloads"] = sorted(
                    workloads.values(), key=lambda item: item["kind"]
                )
                # Los hechos se fusionan por rango de evidencia, igual que las cargas de
                # trabajo. Un informe de sonda solo observa `detected`; si se aceptara tal
                # cual borraría los hechos `tested` que dejó un job ya ejecutado en este
                # nodo, y el planificador dejaría de poder despachar entrenamientos.
                facts: dict[str, dict[str, Any]] = {}
                for item in [*existing.get("facts", []), *merged.get("facts", [])]:
                    if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                        continue
                    previous = facts.get(item["key"])
                    if previous is None or _EVIDENCE_RANK.get(
                        item.get("status"), -1
                    ) >= _EVIDENCE_RANK.get(previous.get("status"), -1):
                        facts[item["key"]] = item
                merged["facts"] = sorted(facts.values(), key=lambda item: item["key"])
                encoded_capabilities = canonical_json(merged)
            changed = db.execute(
                """UPDATE nodes SET status='online', last_heartbeat_at=?,
                   capabilities_json=COALESCE(?, capabilities_json) WHERE node_id=?""",
                (now, encoded_capabilities, node_id),
            ).rowcount
            if not changed:
                raise CoordinatorConflict("node is not registered")
        return {"coordinator_time": now, "next_heartbeat_seconds": 15}
