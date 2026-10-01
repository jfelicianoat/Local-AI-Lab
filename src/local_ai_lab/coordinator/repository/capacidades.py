"""Lo que cada nodo dice y demuestra saber hacer, y la vision general.

La evidencia tiene rango: lo declarado no pisa a lo medido. Por eso
`_EVIDENCE_RANK` existe y por eso un benchmark manda sobre un anuncio.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from local_ai_lab.capabilities.environment import revalidated
from local_ai_lab.domain.common import canonical_json, utc_timestamp
from local_ai_lab.coordinator.repository.trabajos import TrabajosMixin


def _capability_warning(capabilities_json: str | None) -> str | None:
    environment = json.loads(capabilities_json).get("_environment", {}) if capabilities_json else {}
    if not environment.get("invalidated"):
        return None
    if "legacy_unvalidated_result" in environment.get("changed_keys", []):
        return ("Hay pruebas anteriores sin validar. Repite las pruebas afectadas y el preflight antes de entrenar; "
                "los archivos anteriores se conservan.")
    return ("El entorno del Worker cambió. Vuelve a probar las capacidades afectadas; "
            "para entrenar, repite el preflight.")


class CapacidadesMixin(TrabajosMixin):
    """Lo que cada nodo dice y demuestra saber hacer, y la vision general."""

    def node_record(self, node_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        return dict(row) if row else None

    def record_workload_evidence(
        self, node_id: str, *, kind: str, status: str, evidence_sha256: str,
        expected_environment_generation: int | None = None,
    ) -> bool:
        if status not in {"tested", "benchmarked"} or len(evidence_sha256) != 64:
            raise ValueError("workload evidence requires tested/benchmarked status and SHA-256")
        with self.transaction() as db:
            row = db.execute(
                "SELECT capabilities_json, environment_generation, status FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown node: {node_id}")
            if row["status"] == "revoked" or (expected_environment_generation is not None
                    and row["environment_generation"] != expected_environment_generation):
                return False
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
            revalidated(capabilities, f"workload:{kind}")
            db.execute(
                "UPDATE nodes SET capabilities_json=? WHERE node_id=?",
                (canonical_json(capabilities), node_id),
            )
        return True

    def record_capability_facts(
        self, node_id: str, *, facts: Sequence[Mapping[str, Any]], source: str,
        expected_environment_generation: int | None = None,
    ) -> bool:
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
            return False
        replaced = {fact["key"] for fact in prepared}
        with self.transaction() as db:
            row = db.execute(
                "SELECT capabilities_json, environment_generation, status FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown node: {node_id}")
            if row["status"] == "revoked" or (expected_environment_generation is not None
                    and row["environment_generation"] != expected_environment_generation):
                return False
            capabilities = json.loads(row["capabilities_json"]) if row["capabilities_json"] else {}
            kept = [
                item for item in capabilities.get("facts", [])
                if isinstance(item, dict) and item.get("key") not in replaced
            ]
            capabilities["facts"] = sorted(
                [*kept, *prepared], key=lambda item: item.get("key", "")
            )
            revalidated(capabilities, *(f"fact:{key}" for key in replaced))
            db.execute(
                "UPDATE nodes SET capabilities_json=? WHERE node_id=?",
                (canonical_json(capabilities), node_id),
            )
        return True

    def overview(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.connect() as db:
            nodes = [
                {
                    "node_id": row["node_id"],
                    "hostname": row["hostname"],
                    "status": (
                        "offline" if row["status"] == "online" and
                        now - datetime.fromisoformat(row["last_heartbeat_at"].replace("Z", "+00:00")) > timedelta(seconds=90)
                        else row["status"]
                    ),
                    "last_heartbeat_at": row["last_heartbeat_at"],
                    "capabilities_observed": row["capabilities_json"] is not None,
                    "capability_warning": _capability_warning(row["capabilities_json"]),
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
            broker = db.execute(
                "SELECT status FROM product_records WHERE category='experiment' "
                "AND json_extract(summary_json, '$.phase') IN "
                "('phase0','retrieval','formal_evaluation','agent_experiments','demonstrable_execution') "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            vault_ready = db.execute(
                "SELECT 1 FROM product_records WHERE category='snapshot' AND status='COMPLETE' LIMIT 1"
            ).fetchone() is not None
            drift_ready = db.execute(
                "SELECT 1 FROM product_records WHERE category='comparison' "
                "AND status='MODEL_DRIFT_VERIFIED' LIMIT 1"
            ).fetchone() is not None
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
        dependencies = {
            "ai_broker": (
                "verified" if broker and broker["status"] == "CAPABILITIES_SATISFIED" else
                "upgrade_required" if broker and broker["status"] == "UPGRADE_REQUIRED" else "unknown"
            ),
            "vault": "verified" if vault_ready else "unknown",
            "model_drift": "verified" if drift_ready else "unknown",
        }
        return {
            "schema_version": "local-ai-lab.overview.v1",
            "observed_at": utc_timestamp(),
            "phase": "phase1",
            "gate_status": "ready" if all(item["status"] == "tested" for item in evidence)
                and any(node["status"] == "online" for node in nodes) else "pending_real_nodes",
            "nodes": nodes,
            "job_counts": counts,
            "evidence": evidence,
            "external_dependencies": dependencies,
        }
