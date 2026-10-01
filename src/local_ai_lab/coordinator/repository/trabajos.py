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
                "SELECT capabilities_json, environment_generation FROM nodes WHERE node_id=?", (node_id,)
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
                    lease_generation=?, lease_token_hash=?, lease_expires_at=?, updated_at=?,
                    environment_generation=?
                   WHERE job_id=? AND state=?""",
                (
                    JobState.LEASED,
                    node_id,
                    attempt_id,
                    generation,
                    sha256_text(token),
                    expires.isoformat().replace("+00:00", "Z"),
                    now.isoformat().replace("+00:00", "Z"),
                    node["environment_generation"],
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
            target = (JobState.CANCELLED if current in {
                JobState.DRAFT, JobState.READY, JobState.NEEDS_REVIEW,
            } else JobState.CANCELLING)
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
        result_validation_version: int = 0,
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
                f"UPDATE jobs SET state=?, {column}=?, result_validation_version=?, updated_at=? WHERE job_id=?",
                (final, canonical_json(payload), result_validation_version, utc_timestamp(), job_id),
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

    def orphaned_jobs(self) -> list[str]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT job_id FROM jobs WHERE state=? ORDER BY updated_at, job_id",
                (JobState.ORPHANED,),
            ).fetchall()
        return [row["job_id"] for row in rows]

    def record_training_checkpoint(
        self, *, job_id: str, node_id: str, attempt_id: str,
        lease_token: str, lease_generation: int, step: int,
        artifact_id: str, artifact_sha256: str,
    ) -> dict[str, Any]:
        with self.transaction() as db:
            job = self._locked_job(db, job_id)
            self._validate_lease(job, node_id, lease_token, lease_generation)
            if job["attempt_id"] != attempt_id or json.loads(job["spec_json"])["kind"] not in {
                "training.lora.v1", "training.distillation.v1",
            } or step < 1:
                raise CoordinatorConflict("checkpoint does not belong to this training attempt")
            owner = db.execute(
                "SELECT * FROM artifact_upload_owners WHERE artifact_id=?", (artifact_id,),
            ).fetchone()
            if (owner is None or owner["node_id"] != node_id or owner["job_id"] != job_id
                    or owner["attempt_id"] != attempt_id
                    or owner["lease_generation"] != lease_generation
                    or owner["sha256"] != artifact_sha256):
                raise CoordinatorConflict("checkpoint artifact is not owned by this attempt")
            existing = db.execute(
                "SELECT * FROM training_checkpoints WHERE job_id=? AND attempt_id=? AND step=?",
                (job_id, attempt_id, step),
            ).fetchone()
            if existing is not None:
                if (existing["artifact_id"] != artifact_id
                        or existing["artifact_sha256"] != artifact_sha256):
                    raise CoordinatorConflict("checkpoint step already has different evidence")
                return dict(existing)
            checkpoint_id = new_id()
            created_at = utc_timestamp()
            db.execute(
                """INSERT INTO training_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (checkpoint_id, job_id, attempt_id, lease_generation, node_id,
                 step, artifact_id, artifact_sha256, created_at),
            )
        return {
            "checkpoint_id": checkpoint_id, "job_id": job_id, "attempt_id": attempt_id,
            "lease_generation": lease_generation, "node_id": node_id, "step": step,
            "artifact_id": artifact_id, "artifact_sha256": artifact_sha256,
            "created_at": created_at,
        }

    def training_checkpoints(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT c.*, r.resumed_job_id FROM training_checkpoints c
                   LEFT JOIN training_resume_links r ON r.checkpoint_id=c.checkpoint_id
                   WHERE c.job_id=? ORDER BY c.step DESC, c.created_at DESC""",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recovery_node_eligible(self, node_id: str, requirements: dict[str, Any]) -> bool:
        with self.connect() as db:
            node = db.execute(
                "SELECT status, capabilities_json FROM nodes WHERE node_id=?", (node_id,),
            ).fetchone()
        if node is None or node["status"] != "online":
            return False
        capabilities = json.loads(node["capabilities_json"]) if node["capabilities_json"] else {}
        return _requirements_satisfied(
            {**requirements, "node_ids": [node_id]}, capabilities, node_id=node_id,
        )

    def training_resume_link(self, checkpoint_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM training_resume_links WHERE checkpoint_id=?", (checkpoint_id,),
            ).fetchone()
        return dict(row) if row else None

    def training_restart_link(self, source_job_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM training_restart_links WHERE source_job_id=?",
                (source_job_id,),
            ).fetchone()
        return dict(row) if row else None

    def resume_training_from_checkpoint(
        self, *, source_job_id: str, checkpoint_id: str,
        spec: JobSpec, target_node_id: str, authorization_key: str,
    ) -> dict[str, Any]:
        """Publish one operator-approved replacement and its product record atomically."""
        now = utc_timestamp()
        with self.transaction() as db:
            checkpoint = db.execute(
                "SELECT * FROM training_checkpoints WHERE checkpoint_id=? AND job_id=?",
                (checkpoint_id, source_job_id),
            ).fetchone()
            if checkpoint is None:
                raise CoordinatorConflict("checkpoint does not belong to the source job")
            link = db.execute(
                "SELECT * FROM training_resume_links WHERE checkpoint_id=?", (checkpoint_id,),
            ).fetchone()
            if link is not None:
                if (link["authorization_key"] != authorization_key
                        or link["target_node_id"] != target_node_id):
                    raise CoordinatorConflict("checkpoint already has an approved recovery")
                return {"job_id": link["resumed_job_id"], "source_job_id": source_job_id,
                        "checkpoint_id": checkpoint_id, "replayed": True}
            if db.execute(
                "SELECT 1 FROM training_resume_links WHERE source_job_id=?",
                (source_job_id,),
            ).fetchone() or db.execute(
                "SELECT 1 FROM training_restart_links WHERE source_job_id=?",
                (source_job_id,),
            ).fetchone():
                raise CoordinatorConflict("training already has an approved recovery")
            source = self._locked_job(db, source_job_id)
            if source["state"] not in {JobState.NEEDS_REVIEW, JobState.FAILED}:
                raise CoordinatorConflict("training must need review or have failed before recovery")
            if json.loads(source["spec_json"])["kind"] != spec.kind or spec.kind not in {
                "training.lora.v1", "training.distillation.v1",
            }:
                raise CoordinatorConflict("recovery training kind differs from source")
            db.execute(
                """INSERT INTO jobs(job_id, spec_json, spec_fingerprint, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (spec.job_id, canonical_json(asdict(spec)), spec.fingerprint(),
                 JobState.READY, now, now),
            )
            db.execute(
                "INSERT INTO training_resume_links VALUES (?, ?, ?, ?, ?, ?)",
                (checkpoint_id, source_job_id, spec.job_id, target_node_id,
                 authorization_key, now),
            )
            if source["state"] == JobState.NEEDS_REVIEW:
                db.execute(
                    "UPDATE jobs SET state=?, updated_at=? WHERE job_id=?",
                    (JobState.SUPERSEDED, now, source_job_id),
                )
            original_record = db.execute(
                "SELECT * FROM product_records WHERE record_id=?", (source_job_id,),
            ).fetchone()
            old_summary = json.loads(original_record["summary_json"]) if original_record else {}
            title = (original_record["title"] if original_record else
                     "Entrenamiento LoRA" if spec.kind == "training.lora.v1" else "Destilación")
            new_summary = {
                **old_summary, "job_id": spec.job_id, "state": "TRAINING_QUEUED",
                "recovery_source_job_id": source_job_id,
                "recovery_checkpoint_id": checkpoint_id,
                "recovery_step": checkpoint["step"],
                "recovery_target_node_id": target_node_id,
            }
            db.execute(
                "INSERT INTO product_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (spec.job_id, "training", f"{title} (reanudado)", "TRAINING_QUEUED",
                 spec.fingerprint(), canonical_json(new_summary), now, now),
            )
            if original_record:
                old_summary["resumed_by_job_id"] = spec.job_id
                db.execute(
                    "UPDATE product_records SET summary_json=?, updated_at=? WHERE record_id=?",
                    (canonical_json(old_summary), now, source_job_id),
                )
        return {"job_id": spec.job_id, "source_job_id": source_job_id,
                "checkpoint_id": checkpoint_id, "replayed": False}

    def restart_training_job(
        self, *, source_job_id: str, spec: JobSpec,
        target_node_id: str, authorization_key: str,
    ) -> dict[str, Any]:
        now = utc_timestamp()
        with self.transaction() as db:
            link = db.execute(
                "SELECT * FROM training_restart_links WHERE source_job_id=?", (source_job_id,),
            ).fetchone()
            if link is not None:
                if (link["authorization_key"] != authorization_key
                        or link["target_node_id"] != target_node_id):
                    raise CoordinatorConflict("training already has an approved restart")
                return {"job_id": link["restarted_job_id"],
                        "source_job_id": source_job_id, "replayed": True}
            if db.execute(
                "SELECT 1 FROM training_resume_links WHERE source_job_id=?",
                (source_job_id,),
            ).fetchone():
                raise CoordinatorConflict("training already has an approved recovery")
            source = self._locked_job(db, source_job_id)
            if source["state"] not in {JobState.NEEDS_REVIEW, JobState.FAILED}:
                raise CoordinatorConflict("training must need review or have failed before restart")
            if json.loads(source["spec_json"])["kind"] != spec.kind or spec.kind not in {
                "training.lora.v1", "training.distillation.v1",
            }:
                raise CoordinatorConflict("restart training kind differs from source")
            db.execute(
                """INSERT INTO jobs(job_id, spec_json, spec_fingerprint, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (spec.job_id, canonical_json(asdict(spec)), spec.fingerprint(),
                 JobState.READY, now, now),
            )
            db.execute(
                "INSERT INTO training_restart_links VALUES (?, ?, ?, ?, ?)",
                (source_job_id, spec.job_id, target_node_id, authorization_key, now),
            )
            if source["state"] == JobState.NEEDS_REVIEW:
                db.execute(
                    "UPDATE jobs SET state=?, updated_at=? WHERE job_id=?",
                    (JobState.SUPERSEDED, now, source_job_id),
                )
            original_record = db.execute(
                "SELECT * FROM product_records WHERE record_id=?", (source_job_id,),
            ).fetchone()
            old_summary = json.loads(original_record["summary_json"]) if original_record else {}
            title = (original_record["title"] if original_record else
                     "Entrenamiento LoRA" if spec.kind == "training.lora.v1" else "Destilación")
            new_summary = {
                **old_summary, "job_id": spec.job_id, "state": "TRAINING_QUEUED",
                "recovery_source_job_id": source_job_id,
                "recovery_method": "restart_from_start",
                "recovery_target_node_id": target_node_id,
            }
            db.execute(
                "INSERT INTO product_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (spec.job_id, "training", f"{title} (reiniciado)", "TRAINING_QUEUED",
                 spec.fingerprint(), canonical_json(new_summary), now, now),
            )
            if original_record:
                old_summary["restarted_by_job_id"] = spec.job_id
                db.execute(
                    "UPDATE product_records SET summary_json=?, updated_at=? WHERE record_id=?",
                    (canonical_json(old_summary), now, source_job_id),
                )
        return {"job_id": spec.job_id, "source_job_id": source_job_id,
                "replayed": False}

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

    def jobs_page(
        self, *, limit: int = 50, cursor: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ValueError("job page size must be between 1 and 200")
        if cursor is not None and (set(cursor) != {"updated_at", "id"} or
                                   not all(isinstance(value, str) and value for value in cursor.values())):
            raise ValueError("invalid job cursor")
        clause = "WHERE updated_at < ? OR (updated_at = ? AND job_id > ?)" if cursor else ""
        params = (cursor["updated_at"], cursor["updated_at"], cursor["id"]) if cursor else ()
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            rows = db.execute(
                f"SELECT * FROM jobs {clause} ORDER BY updated_at DESC, job_id ASC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            selected = rows[:limit]
            items = []
            for row in selected:
                spec = json.loads(row["spec_json"])
                progress = db.execute(
                    "SELECT payload_json FROM progress_events WHERE job_id=? "
                    "ORDER BY sequence DESC LIMIT 1", (row["job_id"],),
                ).fetchone()
                items.append({
                    "job_id": row["job_id"], "kind": spec["kind"],
                    "state": row["state"], "correlation_id": spec["correlation_id"],
                    "assigned_node_id": row["assigned_node_id"],
                    "lease_generation": row["lease_generation"],
                    "control_action": row["control_action"],
                    "latest_progress": json.loads(progress["payload_json"]) if progress else None,
                    "created_at": row["created_at"], "updated_at": row["updated_at"],
                })
        last = selected[-1] if selected else None
        return {"items": items, "pagination": {
            "total": total, "has_more": len(rows) > limit,
            "cursor": {"updated_at": last["updated_at"], "id": last["job_id"]} if last else None,
        }}
