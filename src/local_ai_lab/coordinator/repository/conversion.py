"""Decodificacion de especificaciones y comprobacion de requisitos.

Funciones puras: no tocan la base y por eso se pueden probar sin abrirla.
"""
from __future__ import annotations

import json
from typing import Any

from local_ai_lab.domain.jobs import JobSpec


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
