"""Bind measured capabilities to the environment in which they were observed."""
from __future__ import annotations

from typing import Any

from local_ai_lab.domain.common import canonical_json, sha256_text


_VOLATILE_GPU_FIELDS = {"temperature_c", "performance_state", "memory_free_mib", "utilization"}
_FACT_RANK = {"declared": 0, "detected": 1, "tested": 2, "benchmarked": 3}


def is_environment_fact(key: str) -> bool:
    if key.startswith("gpu."):
        return key.rsplit(".", 1)[-1] not in _VOLATILE_GPU_FIELDS
    return key.startswith(("os.", "runtime.", "cpu.", "compute.")) or key in {
        "node.hostname", "memory.physical_total_bytes", "storage.data_root", "storage.total_bytes",
    }


def merge_capability_report(
    existing: dict[str, Any], incoming: dict[str, Any], *, generation: int, now: str,
) -> tuple[dict[str, Any], list[str]]:
    """Keep proof on unchanged observations, invalidate it on a stable change.

    A versioned probe is a complete snapshot, including missing dependencies.
    Legacy partial reports only replace the keys they contain. Report IDs,
    timestamps, temperature, free memory and free disk space are not identity.
    Heartbeats can detect capabilities; only accepted job results prove them.
    """
    old_facts = {item["key"]: item for item in existing.get("facts", [])
                 if isinstance(item, dict) and isinstance(item.get("key"), str)}
    new_facts = {item["key"]: dict(item) for item in incoming.get("facts", [])
                 if isinstance(item, dict) and isinstance(item.get("key"), str)}
    previous = existing.get("_environment", {})
    observed = previous.get("facts")
    if not isinstance(observed, dict):
        observed = {key: item.get("value") for key, item in old_facts.items()
                    if is_environment_fact(key)}
    full = isinstance(incoming.get("schema_version"), str) and isinstance(incoming.get("facts"), list)
    current = {} if full else dict(observed)
    current.update({key: item.get("value") for key, item in new_facts.items()
                    if is_environment_fact(key)})
    has_proof = any(item.get("status") in {"tested", "benchmarked"} for item in [
        *old_facts.values(), *existing.get("workloads", []),
    ] if isinstance(item, dict))
    changed = sorted(key for key in observed.keys() | current.keys()
                     if (key not in observed or key not in current
                         or canonical_json(observed[key]) != canonical_json(current[key])))
    # A first observation on a new Worker establishes identity without invalidation.
    if not observed and not has_proof:
        changed = []
    # Also catch a changed value demonstrated by a job but absent from the probe.
    changed = sorted(set(changed) | {
        key for key, item in new_facts.items() if key in old_facts
        and old_facts[key].get("status") in {"tested", "benchmarked"}
        and canonical_json(item.get("value")) != canonical_json(old_facts[key].get("value"))
    })
    invalidated = set(previous.get("invalidated", []))
    facts = {}
    for key, item in old_facts.items():
        if changed and item.get("status") in {"tested", "benchmarked"}:
            invalidated.add(f"fact:{key}")
            continue
        if (full and is_environment_fact(key) and key not in new_facts
                and item.get("status") not in {"tested", "benchmarked"}):
            continue
        facts[key] = item
    for key, item in new_facts.items():
        if item.get("status") in {"tested", "benchmarked"}:
            item["status"] = "detected"
        prior = facts.get(key)
        if prior is None or prior.get("value") != item.get("value") or _FACT_RANK.get(
            item.get("status"), -1
        ) >= _FACT_RANK.get(prior.get("status"), -1):
            facts[key] = item
    workloads = {}
    for item in existing.get("workloads", []):
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            continue
        if changed and item.get("status") in {"tested", "benchmarked"}:
            invalidated.add(f"workload:{item['kind']}")
            item = {**item, "status": "untested"}
        workloads[item["kind"]] = item
    for item in incoming.get("workloads", []):
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            continue
        if item["kind"] not in workloads:
            workloads[item["kind"]] = {**item, "status": "untested"}
    merged = {**incoming, "facts": sorted(facts.values(), key=lambda item: item["key"]),
              "workloads": sorted(workloads.values(), key=lambda item: item["kind"])}
    merged["_environment"] = {
        "generation": generation + bool(changed), "facts": current,
        "fingerprint": sha256_text(canonical_json(current)),
        "changed_at": now if changed else previous.get("changed_at"),
        "changed_keys": changed if changed else previous.get("changed_keys", []),
        "invalidated": sorted(invalidated),
    }
    return merged, changed


def revalidated(capabilities: dict[str, Any], *items: str) -> None:
    environment = capabilities.get("_environment")
    if isinstance(environment, dict):
        environment["invalidated"] = sorted(set(environment.get("invalidated", [])) - set(items))
