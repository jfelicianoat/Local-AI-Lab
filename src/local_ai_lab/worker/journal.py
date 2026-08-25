from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import canonical_json, new_id, sha256_json, utc_timestamp
from local_ai_lab.security.secrets import SecretProtector
from local_ai_lab.storage.sqlite import SQLiteStore


class WorkerJournal(SQLiteStore):
    def __init__(self, path: Path, secret_protector: SecretProtector) -> None:
        super().__init__(path)
        self._secrets = secret_protector
        self._migrate()

    def _migrate(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS local_jobs (
                    job_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    lease_generation INTEGER NOT NULL,
                    lease_token_protected BLOB NOT NULL,
                    expires_at TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    local_state TEXT NOT NULL,
                    progress_sequence INTEGER NOT NULL DEFAULT 0,
                    outcome TEXT,
                    result_json TEXT,
                    result_hash TEXT,
                    sync_state TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    message_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(delivered_at, created_at);
                """
            )

    def accept_lease(self, lease: dict[str, Any]) -> dict[str, Any]:
        spec = lease["spec"]
        now = utc_timestamp()
        with self.transaction() as db:
            existing = db.execute(
                "SELECT attempt_id, spec_hash FROM local_jobs WHERE job_id=?",
                (lease["job_id"],),
            ).fetchone()
            digest = sha256_json(spec)
            if existing:
                if existing["attempt_id"] != lease["attempt_id"] or existing["spec_hash"] != digest:
                    raise ValueError("local job identity conflicts with claimed lease")
                return {"job_id": lease["job_id"], "persisted": True, "replayed": True}
            db.execute(
                """INSERT INTO local_jobs(job_id, attempt_id, lease_generation, lease_token_protected,
                   expires_at, spec_json, spec_hash, local_state, sync_state, accepted_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'accepted', 'pending_ack', ?, ?)""",
                (
                    lease["job_id"], lease["attempt_id"], lease["lease_generation"],
                    self._secrets.protect(lease["lease_token"]), lease["expires_at"],
                    canonical_json(spec), digest, now, now,
                ),
            )
        return {"job_id": lease["job_id"], "persisted": True, "replayed": False}

    def mark_acknowledged(self, job_id: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE local_jobs SET local_state='acknowledged', sync_state='synced', updated_at=? WHERE job_id=?",
                (utc_timestamp(), job_id),
            )

    def mark_running(self, job_id: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE local_jobs SET local_state='running', updated_at=? WHERE job_id=?",
                (utc_timestamp(), job_id),
            )

    def record_progress(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute(
                "SELECT progress_sequence FROM local_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            sequence = int(row["progress_sequence"]) + 1
            message = {
                "job_id": job_id,
                "sequence": sequence,
                "payload": payload,
            }
            key = f"progress:{job_id}:{sequence}"
            db.execute(
                "UPDATE local_jobs SET progress_sequence=?, updated_at=? WHERE job_id=?",
                (sequence, utc_timestamp(), job_id),
            )
            self._enqueue(db, job_id, "progress", key, message)
        return message

    def finish(self, job_id: str, outcome: str, payload: dict[str, Any]) -> dict[str, Any]:
        if outcome not in ("succeeded", "failed", "cancelled"):
            raise ValueError("outcome must be succeeded, failed, or cancelled")
        encoded = canonical_json(payload)
        digest = sha256_json(payload)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM local_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            message = {
                "job_id": job_id,
                "attempt_id": row["attempt_id"],
                "lease_generation": row["lease_generation"],
                "outcome": outcome,
                "payload": payload,
                "result_hash": digest,
            }
            db.execute(
                """UPDATE local_jobs SET local_state=?, outcome=?, result_json=?, result_hash=?,
                   sync_state='pending_result', updated_at=? WHERE job_id=?""",
                (f"{outcome}_pending_sync", outcome, encoded, digest, utc_timestamp(), job_id),
            )
            self._enqueue(
                db, job_id, "complete", f"complete:{job_id}:{row['attempt_id']}", message
            )
        return message

    def pending_messages(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM outbox WHERE delivered_at IS NULL ORDER BY created_at"
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def pending_job_ids(self) -> list[str]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT DISTINCT job_id FROM outbox WHERE delivered_at IS NULL ORDER BY job_id"
            ).fetchall()
        return [row["job_id"] for row in rows]

    def mark_delivered(self, message_id: str) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT job_id, kind FROM outbox WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                return
            db.execute(
                "UPDATE outbox SET delivered_at=? WHERE message_id=?",
                (utc_timestamp(), message_id),
            )
            if row["kind"] == "complete":
                db.execute(
                    "UPDATE local_jobs SET local_state=outcome, sync_state='synced', updated_at=? WHERE job_id=?",
                    (utc_timestamp(), row["job_id"]),
                )

    def replace_outbox_payload(self, message_id: str, payload: dict[str, Any]) -> None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT delivered_at FROM outbox WHERE message_id=?", (message_id,)
            ).fetchone()
            if row is None or row["delivered_at"] is not None:
                raise ValueError("only a pending outbox message can be replaced")
            db.execute(
                "UPDATE outbox SET payload_json=? WHERE message_id=?",
                (canonical_json(payload), message_id),
            )

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM local_jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def lease(self, job_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM local_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return {
            "job_id": row["job_id"],
            "attempt_id": row["attempt_id"],
            "lease_generation": row["lease_generation"],
            "lease_token": self._secrets.unprotect(bytes(row["lease_token_protected"])),
            "expires_at": row["expires_at"],
            "spec": json.loads(row["spec_json"]),
        }

    @staticmethod
    def _enqueue(db: Any, job_id: str, kind: str, key: str, payload: dict[str, Any]) -> None:
        db.execute(
            """INSERT INTO outbox(message_id, job_id, kind, idempotency_key, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(idempotency_key) DO NOTHING""",
            (new_id(), job_id, kind, key, canonical_json(payload), utc_timestamp()),
        )
