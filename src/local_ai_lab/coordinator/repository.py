from __future__ import annotations

import json
import secrets
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import canonical_json, new_id, sha256_text, utc_timestamp
from local_ai_lab.domain.jobs import TERMINAL_STATES, JobSpec, JobState, LeaseGrant, assert_transition
from local_ai_lab.storage.sqlite import SQLiteStore


class CoordinatorConflict(RuntimeError):
    pass


class LeaseRejected(CoordinatorConflict):
    pass


class CoordinatorRepository(SQLiteStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._migrate()

    def _migrate(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    protocol_min INTEGER NOT NULL,
                    protocol_max INTEGER NOT NULL,
                    auth_token_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    capabilities_json TEXT,
                    registered_at TEXT NOT NULL,
                    last_heartbeat_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    spec_json TEXT NOT NULL,
                    spec_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    assigned_node_id TEXT,
                    attempt_id TEXT,
                    lease_generation INTEGER NOT NULL DEFAULT 0,
                    lease_token_hash TEXT,
                    lease_expires_at TEXT,
                    control_action TEXT,
                    result_json TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (assigned_node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS progress_events (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    lease_generation INTEGER NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(job_id, attempt_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS stale_attempts (
                    stale_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    lease_generation INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    scope TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(scope, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_version TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    correlation_id TEXT,
                    references_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS phase_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS product_records (
                    record_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifact_locations (
                    record_id TEXT PRIMARY KEY REFERENCES product_records(record_id),
                    artifact_kind TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at);
                CREATE INDEX IF NOT EXISTS idx_progress_job ON progress_events(job_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_product_records_category
                    ON product_records(category, updated_at);
                """
            )

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
                encoded_capabilities = canonical_json(merged)
            changed = db.execute(
                """UPDATE nodes SET status='online', last_heartbeat_at=?,
                   capabilities_json=COALESCE(?, capabilities_json) WHERE node_id=?""",
                (now, encoded_capabilities, node_id),
            ).rowcount
            if not changed:
                raise CoordinatorConflict("node is not registered")
        return {"coordinator_time": now, "next_heartbeat_seconds": 15}

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

    def node_record(self, node_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        return dict(row) if row else None

    def record_workload_evidence(
        self, node_id: str, *, kind: str, status: str, evidence_sha256: str
    ) -> None:
        if status not in {"tested", "benchmarked"} or len(evidence_sha256) != 64:
            raise ValueError("workload evidence requires tested/benchmarked status and SHA-256")
        with self.transaction() as db:
            row = db.execute(
                "SELECT capabilities_json FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown node: {node_id}")
            capabilities = json.loads(row["capabilities_json"]) if row["capabilities_json"] else {}
            workloads = [
                item for item in capabilities.get("workloads", [])
                if isinstance(item, dict) and item.get("kind") != kind
            ]
            workloads.append({
                "kind": kind, "status": status,
                "evidence_sha256": evidence_sha256, "observed_at": utc_timestamp(),
            })
            capabilities["workloads"] = sorted(workloads, key=lambda item: item.get("kind", ""))
            db.execute(
                "UPDATE nodes SET capabilities_json=? WHERE node_id=?",
                (canonical_json(capabilities), node_id),
            )

    def overview(self) -> dict[str, Any]:
        with self.connect() as db:
            nodes = [
                {
                    "node_id": row["node_id"],
                    "hostname": row["hostname"],
                    "status": row["status"],
                    "last_heartbeat_at": row["last_heartbeat_at"],
                    "capabilities_observed": row["capabilities_json"] is not None,
                    "tested_workloads": sorted(
                        item["kind"]
                        for item in (
                            json.loads(row["capabilities_json"]).get("workloads", [])
                            if row["capabilities_json"] else []
                        )
                        if isinstance(item, dict)
                        and isinstance(item.get("kind"), str)
                        and item.get("status") in {"tested", "benchmarked"}
                    ),
                }
                for row in db.execute(
                    "SELECT node_id, hostname, status, last_heartbeat_at, capabilities_json "
                    "FROM nodes ORDER BY hostname"
                ).fetchall()
            ]
            counts = {
                row["state"]: row["count"]
                for row in db.execute(
                    "SELECT state, COUNT(*) AS count FROM jobs GROUP BY state"
                ).fetchall()
            }
            recorded_evidence = {
                row["evidence_id"]: dict(row)
                for row in db.execute("SELECT * FROM phase_evidence").fetchall()
            }
        requirements = [
            ("phase1.core", "Núcleo distribuido"),
            ("phase1.nvidia", "Worker NVIDIA real"),
            ("phase1.amd", "Worker AMD real"),
            ("phase1.disconnect", "Recuperación real entre PCs"),
            ("phase1.tls", "Conexión segura entre equipos"),
        ]
        evidence = []
        for evidence_id, label in requirements:
            record = recorded_evidence.get(evidence_id)
            evidence.append(
                {
                    "id": evidence_id,
                    "label": label,
                    "status": record["status"] if record else "pending",
                    "artifact_sha256": record["artifact_sha256"] if record else None,
                    "source_reference": record["source_reference"] if record else None,
                    "observed_at": record["observed_at"] if record else None,
                }
            )
        return {
            "schema_version": "local-ai-lab.overview.v1",
            "observed_at": utc_timestamp(),
            "phase": "phase1",
            "gate_status": "pending_real_nodes",
            "nodes": nodes,
            "job_counts": counts,
            "evidence": evidence,
            "external_dependencies": {
                "ai_broker": "unknown",
                "vault": "unknown",
                "model_drift": "unknown",
            },
        }

    def record_phase_evidence(
        self,
        *,
        evidence_id: str,
        label: str,
        status: str,
        artifact_sha256: str,
        source_reference: str,
        observed_at: str,
    ) -> dict[str, Any]:
        if status not in ("tested", "detected", "blocked"):
            raise ValueError("recorded evidence status must be tested, detected, or blocked")
        if len(artifact_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in artifact_sha256
        ):
            raise ValueError("evidence artifact SHA-256 is invalid")
        with self.transaction() as db:
            db.execute(
                """INSERT INTO phase_evidence VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(evidence_id) DO UPDATE SET label=excluded.label,
                   status=excluded.status, artifact_sha256=excluded.artifact_sha256,
                   source_reference=excluded.source_reference, observed_at=excluded.observed_at""",
                (evidence_id, label, status, artifact_sha256, source_reference, observed_at),
            )
        return {"evidence_id": evidence_id, "status": status, "recorded": True}

    def record_product_item(
        self,
        *,
        record_id: str,
        category: str,
        title: str,
        status: str,
        artifact_sha256: str,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        allowed_categories = {
            "snapshot", "index", "benchmark", "experiment", "comparison", "review",
            "dataset", "training", "export",
        }
        if category not in allowed_categories:
            raise ValueError("unknown product record category")
        if not record_id.strip() or not title.strip() or not status.strip():
            raise ValueError("product record identity, title and status are required")
        if len(artifact_sha256) != 64 or any(char not in "0123456789abcdef" for char in artifact_sha256):
            raise ValueError("product record artifact SHA-256 is invalid")
        now = utc_timestamp()
        with self.transaction() as db:
            db.execute(
                """INSERT INTO product_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(record_id) DO UPDATE SET category=excluded.category,
                   title=excluded.title, status=excluded.status,
                   artifact_sha256=excluded.artifact_sha256,
                   summary_json=excluded.summary_json, updated_at=excluded.updated_at""",
                (record_id, category, title, status, artifact_sha256, canonical_json(summary), now, now),
            )
        return {"record_id": record_id, "category": category, "status": status}

    def product_workspace(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM product_records ORDER BY updated_at DESC, record_id"
            ).fetchall()
        records = [
            {
                "record_id": row["record_id"], "category": row["category"],
                "title": row["title"], "status": row["status"],
                "artifact_sha256": row["artifact_sha256"],
                "summary": json.loads(row["summary_json"]),
                "created_at": row["created_at"], "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        categories = {
            category: [record for record in records if record["category"] == category]
            for category in (
                "snapshot", "index", "benchmark", "experiment", "comparison", "review",
                "dataset", "training", "export",
            )
        }
        return {
            "schema_version": "local-ai-lab.workspace.v1",
            "observed_at": utc_timestamp(),
            "knowledge": categories["snapshot"] + categories["index"],
            "benchmarks": categories["benchmark"],
            "experiments": categories["experiment"] + categories["comparison"],
            "reviews": categories["review"],
            "datasets": categories["dataset"],
            "training": categories["training"],
            "exports": categories["export"],
        }

    def product_record(self, record_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM product_records WHERE record_id=?", (record_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "record_id": row["record_id"], "category": row["category"],
            "title": row["title"], "status": row["status"],
            "artifact_sha256": row["artifact_sha256"],
            "summary": json.loads(row["summary_json"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def record_artifact_location(
        self,
        *,
        record_id: str,
        artifact_kind: str,
        local_path: Path,
        artifact_sha256: str,
    ) -> None:
        path = local_path.resolve(strict=True)
        if str(path).startswith(("\\\\", "//")):
            raise ValueError("artifact locations must be local")
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM product_records WHERE record_id=?", (record_id,)).fetchone() is None:
                raise KeyError(f"unknown product record: {record_id}")
            db.execute(
                """INSERT INTO artifact_locations VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(record_id) DO UPDATE SET artifact_kind=excluded.artifact_kind,
                   local_path=excluded.local_path, artifact_sha256=excluded.artifact_sha256,
                   recorded_at=excluded.recorded_at""",
                (record_id, artifact_kind, str(path), artifact_sha256, utc_timestamp()),
            )

    def artifact_location(self, record_id: str, *, expected_kind: str) -> Path:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM artifact_locations WHERE record_id=?", (record_id,)
            ).fetchone()
        if row is None or row["artifact_kind"] != expected_kind:
            raise KeyError(f"no {expected_kind} location registered for {record_id}")
        path = Path(row["local_path"]).resolve(strict=True)
        if str(path).startswith(("\\\\", "//")):
            raise ValueError("registered artifact location is no longer local")
        return path

    @staticmethod
    def _locked_job(db: Any, job_id: str) -> Any:
        row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise CoordinatorConflict("job does not exist")
        return row

    @staticmethod
    def _validate_lease(
        row: Any, node_id: str, lease_token: str, lease_generation: int
    ) -> None:
        if row["assigned_node_id"] != node_id:
            raise LeaseRejected("job is assigned to another node")
        if int(row["lease_generation"]) != lease_generation:
            raise LeaseRejected("lease fencing generation is stale")
        if not row["lease_token_hash"] or not secrets.compare_digest(
            row["lease_token_hash"], sha256_text(lease_token)
        ):
            raise LeaseRejected("lease token is invalid")


def _decode_spec(encoded: str) -> JobSpec:
    payload = json.loads(encoded)
    from local_ai_lab.domain.jobs import (
        DisconnectPolicy,
        IdempotencyClass,
        ReassignmentPolicy,
    )

    payload["idempotency_class"] = IdempotencyClass(payload["idempotency_class"])
    payload["disconnect_policy"] = DisconnectPolicy(payload["disconnect_policy"])
    payload["reassignment_policy"] = ReassignmentPolicy(payload["reassignment_policy"])
    return JobSpec(**payload)


def _requirements_satisfied(
    requirements: dict[str, Any], capabilities: dict[str, Any], *, node_id: str | None = None
) -> bool:
    if not requirements:
        return True
    allowed_nodes = requirements.get("node_ids", [])
    if allowed_nodes and node_id not in allowed_nodes:
        return False
    facts = {
        item.get("key"): item.get("value")
        for item in capabilities.get("facts", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    for key, expected in requirements.get("required_facts", {}).items():
        actual = facts.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    workloads = {
        item.get("kind")
        for item in capabilities.get("workloads", [])
        if isinstance(item, dict) and item.get("status") in ("tested", "benchmarked")
    }
    return all(kind in workloads for kind in requirements.get("required_workloads", []))
