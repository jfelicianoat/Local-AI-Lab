"""Esquema, conflictos y guardas de lease.

El `_migrate` de aqui es la unica definicion del esquema: mantenerla junta
evita que una tabla nueva aparezca en un modulo y su indice en otro.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import sha256_text
from local_ai_lab.storage.sqlite import SQLiteStore


_EVIDENCE_RANK = {"declared": 0, "detected": 1, "tested": 2, "benchmarked": 3}


class CoordinatorConflict(RuntimeError):
    pass


class LeaseRejected(CoordinatorConflict):
    pass


class RepositorioBase(SQLiteStore):
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
