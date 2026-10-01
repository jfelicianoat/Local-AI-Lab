from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from local_ai_lab.domain.jobs import DisconnectPolicy, IdempotencyClass, JobSpec, ReassignmentPolicy


class ExportJobPlanner:
    def plan(
        self,
        *,
        source_manifest_sha256: str,
        source_artifact_reference: str,
        formats: Sequence[str],
        node_id: str,
        tested_capabilities: set[str],
        verification_only: bool = False,
        detected_dependencies: set[str] | None = None,
    ) -> JobSpec:
        requested = tuple(dict.fromkeys(formats))
        allowed = {"adapter", "merged_model", "safetensors", "gguf"}
        if not requested or not set(requested) <= allowed:
            raise ValueError("unsupported or empty export format list")
        required = {f"export.{kind}" for kind in requested}
        missing = required - tested_capabilities
        if type(verification_only) is not bool:
            raise ValueError("export verification mode must be a boolean")
        if verification_only and set(requested) - {"adapter"}:
            dependencies = {"torch", "transformers", "peft"} - (detected_dependencies or set())
            if dependencies:
                raise ValueError(f"Instala estos paquetes en el Worker seleccionado antes de comprobar la exportación: {', '.join(sorted(dependencies))}")
        if missing and not verification_only:
            raise ValueError(f"node lacks tested export capabilities: {sorted(missing)}")
        if len(source_manifest_sha256) != 64:
            raise ValueError("source training manifest requires SHA-256")
        return JobSpec(
            kind="model.export.v1",
            payload={
                "source_manifest_sha256": source_manifest_sha256,
                "source_artifact_reference": source_artifact_reference,
                "formats": list(requested),
                "verify_after_each_conversion": True,
                "verification_only": verification_only,
            },
            requirements={"node_ids": [node_id], "required_workloads": [] if verification_only else sorted(required)},
            idempotency_class=IdempotencyClass.CHECKPOINTABLE,
            disconnect_policy=DisconnectPolicy.CHECKPOINT_THEN_STOP,
            reassignment_policy=ReassignmentPolicy.HUMAN_ONLY,
        )


@dataclass(frozen=True, slots=True)
class CacheCandidate:
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CacheCleanupPlan:
    cache_root: str
    candidates: tuple[CacheCandidate, ...]
    total_bytes: int
    destructive_execution_available: bool = False


class CacheCleanupPlanner:
    """Produces a reviewable plan only; deletion is deliberately outside this interface."""

    def inspect(self, cache_root: Path, referenced_hashes: set[str]) -> CacheCleanupPlan:
        root = cache_root.resolve(strict=True)
        candidates: list[CacheCandidate] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if digest not in referenced_hashes:
                candidates.append(CacheCandidate(resolved.relative_to(root).as_posix(), resolved.stat().st_size, digest))
        return CacheCleanupPlan(str(root), tuple(candidates), sum(item.size for item in candidates))
