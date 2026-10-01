"""Esquema, conflictos y guardas de lease.

El `_migrate` de aqui es la unica definicion del esquema: mantenerla junta
evita que una tabla nueva aparezca en un modulo y su indice en otro.
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import sha256_text, utc_timestamp
from local_ai_lab.capabilities.environment import is_environment_fact
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
                CREATE TABLE IF NOT EXISTS artifact_upload_owners (
                    artifact_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    lease_generation INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS storage_cleanup_plans (
                    plan_id TEXT PRIMARY KEY,
                    plan_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS retired_artifact_uploads (
                    artifact_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL REFERENCES storage_cleanup_plans(plan_id),
                    retired_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS training_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    attempt_id TEXT NOT NULL,
                    lease_generation INTEGER NOT NULL,
                    node_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, attempt_id, step)
                );
                CREATE TABLE IF NOT EXISTS training_resume_links (
                    checkpoint_id TEXT PRIMARY KEY REFERENCES training_checkpoints(checkpoint_id),
                    source_job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    resumed_job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
                    target_node_id TEXT NOT NULL REFERENCES nodes(node_id),
                    authorization_key TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS training_restart_links (
                    source_job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                    restarted_job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
                    target_node_id TEXT NOT NULL REFERENCES nodes(node_id),
                    authorization_key TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_plans (
                    mission_id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    task TEXT NOT NULL,
                    success TEXT NOT NULL,
                    constraints_text TEXT NOT NULL,
                    teacher_source TEXT,
                    teacher_model TEXT,
                    student_model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_links (
                    mission_id TEXT NOT NULL REFERENCES mission_plans(mission_id),
                    stage_index INTEGER NOT NULL,
                    reference_kind TEXT NOT NULL,
                    reference_id TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    PRIMARY KEY (mission_id, stage_index, reference_kind, reference_id)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_page ON jobs(updated_at DESC, job_id ASC);
                CREATE INDEX IF NOT EXISTS idx_progress_job ON progress_events(job_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_product_records_category
                    ON product_records(category, updated_at);
                CREATE INDEX IF NOT EXISTS idx_product_records_page
                    ON product_records(updated_at DESC, record_id ASC, category);
                CREATE INDEX IF NOT EXISTS idx_product_records_category_page
                    ON product_records(category, updated_at DESC, record_id ASC);
                CREATE INDEX IF NOT EXISTS idx_mission_links_reference
                    ON mission_links(reference_kind, reference_id);
                CREATE INDEX IF NOT EXISTS idx_training_checkpoints_job
                    ON training_checkpoints(job_id, step DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_training_resume_source
                    ON training_resume_links(source_job_id);
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(training_resume_links)")}
            if "target_node_id" not in columns:
                db.execute("ALTER TABLE training_resume_links ADD COLUMN target_node_id TEXT")
                for link in db.execute(
                    "SELECT checkpoint_id, resumed_job_id FROM training_resume_links"
                ).fetchall():
                    resumed = db.execute(
                        "SELECT spec_json FROM jobs WHERE job_id=?", (link["resumed_job_id"],)
                    ).fetchone()
                    checkpoint = db.execute(
                        "SELECT node_id FROM training_checkpoints WHERE checkpoint_id=?",
                        (link["checkpoint_id"],),
                    ).fetchone()
                    selected = (json.loads(resumed["spec_json"]).get("requirements", {})
                                .get("node_ids", []) if resumed else [])
                    node_id = selected[0] if selected else checkpoint["node_id"]
                    db.execute(
                        "UPDATE training_resume_links SET target_node_id=? WHERE checkpoint_id=?",
                        (node_id, link["checkpoint_id"]),
                    )
            migrate_unbound_evidence = False
            for table, column, definition in (
                ("nodes", "environment_generation", "INTEGER NOT NULL DEFAULT 0"),
                ("jobs", "environment_generation", "INTEGER"),
            ):
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    migrate_unbound_evidence |= table == "nodes"
            if migrate_unbound_evidence:
                # Old proof has no environment identity. Retain its historical
                # hashes, but require a fresh preflight before it can schedule ML.
                for node in db.execute("SELECT * FROM nodes").fetchall():
                    capabilities = json.loads(node["capabilities_json"]) if node["capabilities_json"] else {}
                    facts = capabilities.get("facts", [])
                    workloads = capabilities.get("workloads", [])
                    invalidated = [f"fact:{item['key']}" for item in facts if isinstance(item, dict)
                                   and isinstance(item.get("key"), str) and item.get("status") in {"tested", "benchmarked"}]
                    invalidated.extend(f"workload:{item['kind']}" for item in workloads if isinstance(item, dict)
                                       and isinstance(item.get("kind"), str) and item.get("status") in {"tested", "benchmarked"})
                    if invalidated:
                        capabilities["facts"] = [item for item in facts if isinstance(item, dict)
                                                 and item.get("status") not in {"tested", "benchmarked"}]
                        capabilities["workloads"] = [{**item, "status": "untested"} for item in workloads if isinstance(item, dict)]
                        capabilities["_environment"] = {
                            "generation": 1, "changed_at": utc_timestamp(), "changed_keys": ["legacy_unbound_evidence"],
                            "invalidated": sorted(invalidated),
                            "facts": {item["key"]: item.get("value") for item in capabilities["facts"]
                                      if isinstance(item.get("key"), str) and is_environment_fact(item["key"])},
                        }
                        db.execute("UPDATE nodes SET capabilities_json=?, environment_generation=1 WHERE node_id=?",
                                   (json.dumps(capabilities, ensure_ascii=False, sort_keys=True), node["node_id"]))
                    self._invalidate_preflights(db, node["node_id"], 1 if invalidated else 0)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "result_validation_version" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN result_validation_version INTEGER NOT NULL DEFAULT 0")
                # Earlier results could bypass manifest/metric validation.
                # Preserve all historical files/jobs while removing their authority.
                for node in db.execute("SELECT * FROM nodes").fetchall():
                    capabilities = json.loads(node["capabilities_json"]) if node["capabilities_json"] else {}
                    invalidated = []
                    facts = capabilities.get("facts", [])
                    for item in facts:
                        if (isinstance(item, dict) and item.get("status") in {"tested", "benchmarked"}
                                and (str(item.get("key", "")).startswith(("training.", "dtype.")) or item.get("key") == "gpu.backend")):
                            invalidated.append(f"fact:{item['key']}")
                            item["status"] = "detected"
                    for item in capabilities.get("workloads", []):
                        if (isinstance(item, dict) and (str(item.get("kind", "")).startswith(("training.", "export."))
                                or item.get("kind") in {"embeddings.semantic", "broker.single_experiment", "broker.agent_experiment"})
                                and item.get("status") in {"tested", "benchmarked"}):
                            invalidated.append(f"workload:{item['kind']}")
                            item["status"] = "untested"
                    if invalidated:
                        environment = capabilities.setdefault("_environment", {})
                        environment["invalidated"] = sorted(set(environment.get("invalidated", [])) | set(invalidated))
                        environment["changed_keys"] = [*environment.get("changed_keys", []), "legacy_unvalidated_result"]
                        environment["changed_at"] = utc_timestamp()
                        db.execute("UPDATE nodes SET capabilities_json=? WHERE node_id=?",
                                   (json.dumps(capabilities, ensure_ascii=False, sort_keys=True), node["node_id"]))
                db.execute("""UPDATE product_records SET status='RESULT_REQUIRES_VALIDATION',
                           summary_json=json_set(summary_json, '$.state', 'RESULT_REQUIRES_VALIDATION',
                                                 '$.capabilities_validated', json('false')),
                           updated_at=? WHERE status IN (
                               'PREFLIGHT_PASSED', 'TRAINING_SUCCEEDED', 'DISTILLATION_SUCCEEDED', 'EXPORT_SUCCEEDED',
                               'EXPERIMENT_SUCCEEDED')""",
                           (utc_timestamp(),))

    @staticmethod
    def _invalidate_preflights(db: Any, node_id: str, generation: int) -> None:
        db.execute(
            """UPDATE product_records SET status='PREFLIGHT_ENVIRONMENT_CHANGED',
               summary_json=json_set(summary_json, '$.state', 'PREFLIGHT_ENVIRONMENT_CHANGED',
                                     '$.capabilities_validated', json('false')),
               updated_at=? WHERE status='PREFLIGHT_PASSED' AND record_id IN (
                   SELECT job_id FROM jobs WHERE assigned_node_id=?
                   AND (environment_generation IS NULL OR environment_generation!=?)
               )""",
            (utc_timestamp(), node_id, generation),
        )

    @staticmethod
    def _locked_job(db: Any, job_id: str) -> Any:
        row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise CoordinatorConflict("job does not exist")
        return row

    @staticmethod
    def _validate_lease_identity(
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

    @classmethod
    def _validate_lease(
        cls, row: Any, node_id: str, lease_token: str, lease_generation: int
    ) -> None:
        cls._validate_lease_identity(row, node_id, lease_token, lease_generation)
        expiry = row["lease_expires_at"]
        if not expiry or datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(UTC):
            raise LeaseRejected("lease has expired")
