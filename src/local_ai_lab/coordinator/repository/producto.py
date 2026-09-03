"""Registros de producto: evidencias de fase, artefactos y su ubicacion.

Una ubicacion de artefacto que deje de ser local se rechaza al leerla:
el laboratorio no sigue rutas UNC que aparecieron despues.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import canonical_json, utc_timestamp
from local_ai_lab.coordinator.repository.capacidades import CapacidadesMixin


class ProductoMixin(CapacidadesMixin):
    """Registros de producto: evidencias de fase, artefactos y su ubicacion."""

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
