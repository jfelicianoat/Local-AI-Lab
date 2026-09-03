"""Lo que cada nodo dice y demuestra saber hacer, y la vision general.

La evidencia tiene rango: lo declarado no pisa a lo medido. Por eso
`_EVIDENCE_RANK` existe y por eso un benchmark manda sobre un anuncio.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from local_ai_lab.domain.common import canonical_json, utc_timestamp
from local_ai_lab.coordinator.repository.trabajos import TrabajosMixin


class CapacidadesMixin(TrabajosMixin):
    """Lo que cada nodo dice y demuestra saber hacer, y la vision general."""

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

    def record_capability_facts(
        self, node_id: str, *, facts: Sequence[Mapping[str, Any]], source: str
    ) -> None:
        """Guarda hechos que un job ya ejecutado demostró en este nodo.

        La sonda de capacidades solo alcanza `detected` porque no ejecuta cargas ML. Los
        hechos que el planificador exige en `required_facts` (`gpu.backend`, `dtype.*`)
        solo pueden nacer de un job real, y sin ellos ningún Worker puede reclamar un
        entrenamiento ni una destilación.
        """
        prepared: list[dict[str, Any]] = []
        for fact in facts:
            key = fact.get("key")
            status = fact.get("status")
            if not isinstance(key, str) or not key:
                raise ValueError("capability facts require a key")
            if status not in {"tested", "benchmarked"}:
                raise ValueError("recorded capability facts require tested/benchmarked status")
            prepared.append({
                "key": key,
                "value": fact.get("value"),
                "status": status,
                "source": source,
                "observed_at": utc_timestamp(),
                "unit": fact.get("unit"),
                "detail": fact.get("detail"),
            })
        if not prepared:
            return
        replaced = {fact["key"] for fact in prepared}
        with self.transaction() as db:
            row = db.execute(
                "SELECT capabilities_json FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown node: {node_id}")
            capabilities = json.loads(row["capabilities_json"]) if row["capabilities_json"] else {}
            kept = [
                item for item in capabilities.get("facts", [])
                if isinstance(item, dict) and item.get("key") not in replaced
            ]
            capabilities["facts"] = sorted(
                [*kept, *prepared], key=lambda item: item.get("key", "")
            )
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
