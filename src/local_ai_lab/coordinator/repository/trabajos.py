"""Cola de trabajos y su maquina de estados, con leases.

Las transiciones se validan contra `assert_transition` y siempre bajo
lease: un nodo que perdio el suyo no puede escribir el resultado.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from local_ai_lab.domain.common import canonical_json, new_id, sha256_text, utc_timestamp
from local_ai_lab.domain.jobs import TERMINAL_STATES, JobSpec, JobState, LeaseGrant, assert_transition
from local_ai_lab.coordinator.repository.base import (
    CoordinatorConflict,
    LeaseRejected,
)
from local_ai_lab.coordinator.repository.nodos import NodosMixin
from local_ai_lab.coordinator.repository.conversion import _decode_spec, _requirements_satisfied


class TrabajosMixin(NodosMixin):
    """Cola de trabajos y su maquina de estados, con leases."""

    def submit_job(self, spec: JobSpec) -> dict[str, Any]:
        now = utc_timestamp()
        encoded = canonical_json(asdict(spec))
        with self.transaction() as db:
            existing = db.execute(
                "SELECT spec_fingerprint, state FROM jobs WHERE job_id=?", (spec.job_id,)
            ).fetchone()
            if existing:
                if existing["spec_fingerprint"] != spec.fingerprint():
                    raise CoordinatorConflict("job_id already exists with different content")
                return {"job_id": spec.job_id, "state": existing["state"], "replayed": True}
            db.execute(
                """INSERT INTO jobs(job_id, spec_json, spec_fingerprint, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (spec.job_id, encoded, spec.fingerprint(), JobState.READY, now, now),
            )
        return {"job_id": spec.job_id, "state": JobState.READY, "replayed": False}

    def claim_job(self, node_id: str, lease_seconds: int = 60) -> LeaseGrant | None:
        if lease_seconds < 5 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 5 and 3600")
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = secrets.token_urlsafe(32)
        attempt_id = new_id()
        with self.transaction() as db:
            node = db.execute(
                "SELECT capabilities_json FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if node is None:
                raise CoordinatorConflict("node is not registered")
            capabilities = (
                json.loads(node["capabilities_json"]) if node["capabilities_json"] else {}
            )
            candidates = db.execute(
                "SELECT * FROM jobs WHERE state=? ORDER BY created_at",
                (JobState.READY,),
            ).fetchall()
            row = next(
                (
                    candidate
                    for candidate in candidates
                    if _requirements_satisfied(
                        json.loads(candidate["spec_json"]).get("requirements", {}),
                        capabilities,
                        node_id=node_id,
                    )
                ),
                None,
            )
            if row is None:
                return None
            generation = int(row["lease_generation"]) + 1
            changed = db.execute(
                """UPDATE jobs SET state=?, assigned_node_id=?, attempt_id=?,
                   lease_generation=?, lease_token_hash=?, lease_expires_at=?, updated_at=?
                   WHERE job_id=? AND state=?""",
                (
                    JobState.LEASED,
                    node_id,
                    attempt_id,
                    generation,
                    sha256_text(token),
                    expires.isoformat().replace("+00:00", "Z"),
                    now.isoformat().replace("+00:00", "Z"),
                    row["job_id"],
                    JobState.READY,
                ),
            ).rowcount
            if not changed:
                return None
        return LeaseGrant(
            job_id=row["job_id"],
            attempt_id=attempt_id,
            node_id=node_id,
            lease_token=token,
            lease_generation=generation,
            expires_at=expires.isoformat().replace("+00:00", "Z"),
            spec=_decode_spec(row["spec_json"]),
        )

    def transition_with_lease(
        self,
        *,
        job_id: str,
        node_id: str,
        lease_token: str,
        lease_generation: int,
        target: JobState,
    ) -> dict[str, Any]:
        with self.transaction() as db:
            row = self._locked_job(db, job_id)
            self._validate_lease(row, node_id, lease_token, lease_generation)
            current = JobState(row["state"])
            assert_transition(current, target)
            now = utc_timestamp()
            db.execute("UPDATE jobs SET state=?, updated_at=? WHERE job_id=?", (target, now, job_id))
        return {"job_id": job_id, "state": target, "updated_at": now}

    def renew_lease(
        self,
        *,
        job_id: str,
        node_id: str,
        lease_token: str,
        lease_generation: int,
        lease_seconds: int = 60,
    ) -> dict[str, Any]:
        with self.transaction() as db:
            row = self._locked_job(db, job_id)
            self._validate_lease(row, node_id, lease_token, lease_generation)
            if JobState(row["state"]) not in {
                JobState.LEASED,
                JobState.ACKNOWLEDGED,
                JobState.RUNNING,
                JobState.PAUSING,
                JobState.PAUSED,
                JobState.CANCELLING,
            }:
                raise LeaseRejected("job state does not allow lease renewal")
            expires = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            encoded = expires.isoformat().replace("+00:00", "Z")
            db.execute(
                "UPDATE jobs SET lease_expires_at=?, updated_at=? WHERE job_id=?",
                (encoded, utc_timestamp(), job_id),
            )
        return {"job_id": job_id, "lease_generation": lease_generation, "expires_at": encoded}

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        with self.transaction() as db:
            row = self._locked_job(db, job_id)
            current = JobState(row["state"])
            if current in TERMINAL_STATES:
                return {"job_id": job_id, "state": current, "replayed": True}
            target = JobState.CANCELLED if current in {JobState.DRAFT, JobState.READY} else JobState.CANCELLING
            assert_transition(current, target)
            db.execute(
                "UPDATE jobs SET state=?, control_action='cancel', updated_at=? WHERE job_id=?",
                (target, utc_timestamp(), job_id),
            )
        return {"job_id": job_id, "state": target, "replayed": False}

    def job_control(
        self,
        *,
        job_id: str,
        node_id: str,
        lease_token: str,
        lease_generation: int,
    ) -> dict[str, Any]:
        with self.connect() as db:
            row = self._locked_job(db, job_id)
            self._validate_lease(row, node_id, lease_token, lease_generation)
        return {"job_id": job_id, "action": row["control_action"], "state": row["state"]}

    def record_progress(
        self,
        *,
        job_id: str,
        node_id: str,
        lease_token: str,
        lease_generation: int,
        sequence: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self.transaction() as db:
            row = self._locked_job(db, job_id)
            self._validate_lease(row, node_id, lease_token, lease_generation)
            if JobState(row["state"]) == JobState.ACKNOWLEDGED:
                db.execute(
                    "UPDATE jobs SET state=?, updated_at=? WHERE job_id=?",
                    (JobState.RUNNING, utc_timestamp(), job_id),
                )
            db.execute(
                """INSERT INTO progress_events(event_id, job_id, attempt_id, lease_generation,
                   sequence, payload_json, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id, attempt_id, sequence) DO NOTHING""",
                (
                    new_id(),
                    job_id,
                    row["attempt_id"],
                    lease_generation,
                    sequence,
                    canonical_json(payload),
                    utc_timestamp(),
                ),
            )
        return {"job_id": job_id, "sequence": sequence, "accepted": True}

    def complete(
        self,
        *,
        job_id: str,
        node_id: str,
        attempt_id: str,
        lease_token: str,
        lease_generation: int,
        outcome: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if outcome not in ("succeeded", "failed", "cancelled"):
            raise ValueError("outcome must be succeeded, failed, or cancelled")
        with self.transaction() as db:
            row = self._locked_job(db, job_id)
            try:
                self._validate_lease(row, node_id, lease_token, lease_generation)
                if row["attempt_id"] != attempt_id:
                    raise LeaseRejected("attempt is not current")
            except LeaseRejected:
                db.execute(
                    """INSERT INTO stale_attempts VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_id(), job_id, attempt_id, lease_generation, outcome,
                        canonical_json(payload), utc_timestamp(),
                    ),
                )
                return {"job_id": job_id, "accepted": False, "classification": "stale_attempt"}

            current = JobState(row["state"])
            if outcome == "cancelled":
                if current != JobState.CANCELLING:
                    raise CoordinatorConflict("only a cancelling job can complete as cancelled")
                pending = final = JobState.CANCELLED
            else:
                pending = (
                    JobState.SUCCEEDED_PENDING_SYNC
                    if outcome == "succeeded"
                    else JobState.FAILED_PENDING_SYNC
                )
                final = JobState.SUCCEEDED if outcome == "succeeded" else JobState.FAILED
            if current == JobState.ACKNOWLEDGED:
                assert_transition(current, JobState.RUNNING)
                current = JobState.RUNNING
            assert_transition(current, pending)
            if pending != final:
                assert_transition(pending, final)
            column = "result_json" if outcome in {"succeeded", "cancelled"} else "error_json"
            db.execute(
                f"UPDATE jobs SET state=?, {column}=?, updated_at=? WHERE job_id=?",
                (final, canonical_json(payload), utc_timestamp(), job_id),
            )
        return {"job_id": job_id, "accepted": True, "state": final}

    def expire_leases(self, now: datetime | None = None) -> list[str]:
        instant = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
        active = tuple(
            state.value
            for state in (
                JobState.LEASED,
                JobState.ACKNOWLEDGED,
                JobState.RUNNING,
                JobState.PAUSING,
                JobState.PAUSED,
                JobState.CANCELLING,
            )
        )
        placeholders = ",".join("?" for _ in active)
        with self.transaction() as db:
            rows = db.execute(
                f"SELECT job_id FROM jobs WHERE state IN ({placeholders}) AND lease_expires_at < ?",
                (*active, instant),
            ).fetchall()
            ids = [row["job_id"] for row in rows]
            if ids:
                db.executemany(
                    "UPDATE jobs SET state=?, updated_at=? WHERE job_id=?",
                    [(JobState.ORPHANED, utc_timestamp(), job_id) for job_id in ids],
                )
        return ids

    def reconcile_orphan(self, job_id: str, decision: str) -> dict[str, Any]:
        if decision not in ("requeue", "supersede", "needs_review"):
            raise ValueError("invalid reconciliation decision")
        target = {
            "requeue": JobState.READY,
            "supersede": JobState.SUPERSEDED,
            "needs_review": JobState.NEEDS_REVIEW,
        }[decision]
        with self.transaction() as db:
            row = self._locked_job(db, job_id)
            if JobState(row["state"]) != JobState.ORPHANED:
                raise CoordinatorConflict("only orphaned jobs can be reconciled")
            spec = _decode_spec(row["spec_json"])
            if decision == "requeue" and (
                spec.reassignment_policy.value != "automatic"
                or spec.idempotency_class.value != "pure"
            ):
                raise CoordinatorConflict("this job requires review before reassignment")
            db.execute(
                """UPDATE jobs SET state=?, assigned_node_id=NULL, attempt_id=NULL,
                   lease_token_hash=NULL, lease_expires_at=NULL, updated_at=? WHERE job_id=?""",
                (target, utc_timestamp(), job_id),
            )
        return {"job_id": job_id, "state": target, "decision": decision}

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def jobs_view(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC, job_id"
            ).fetchall()
            latest_progress = {
                row["job_id"]: json.loads(row["payload_json"])
                for row in db.execute(
                    """SELECT progress_events.job_id, progress_events.payload_json
                       FROM progress_events
                       JOIN (
                         SELECT job_id, MAX(sequence) AS sequence
                         FROM progress_events GROUP BY job_id
                       ) latest
                       ON latest.job_id=progress_events.job_id
                       AND latest.sequence=progress_events.sequence"""
                ).fetchall()
            }
        result: list[dict[str, Any]] = []
        for row in rows:
            spec = json.loads(row["spec_json"])
            result.append(
                {
                    "job_id": row["job_id"],
                    "kind": spec["kind"],
                    "state": row["state"],
                    "correlation_id": spec["correlation_id"],
                    "assigned_node_id": row["assigned_node_id"],
                    "lease_generation": row["lease_generation"],
                    "control_action": row["control_action"],
                    "latest_progress": latest_progress.get(row["job_id"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result
