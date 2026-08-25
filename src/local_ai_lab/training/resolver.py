from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from local_ai_lab.capabilities.model import NodeCapabilityReport


@dataclass(frozen=True, slots=True)
class HardwareResolution:
    status: str
    node_id: str | None
    backend: str | None
    dtype: str | None
    reasons: tuple[str, ...]


class TrainingHardwareResolver:
    REQUIRED_TRUE = ("training.lora", "training.backward", "training.checkpoint_resume", "training.twenty_steps")

    def resolve(self, reports: Sequence[NodeCapabilityReport]) -> HardwareResolution:
        viable: list[tuple[float, str, str, str]] = []
        rejected: list[str] = []
        for report in reports:
            facts = {fact.key: fact for fact in report.facts}
            missing = [
                key for key in self.REQUIRED_TRUE
                if key not in facts or facts[key].value is not True or facts[key].status not in {"tested", "benchmarked"}
            ]
            backend = facts.get("gpu.backend")
            if backend is None or backend.status not in {"tested", "benchmarked"}:
                missing.append("gpu.backend")
            dtype = self._dtype(facts)
            if dtype is None:
                missing.append("dtype.bf16_or_fp16")
            memory = facts.get("gpu.usable_memory_gib")
            if memory is None or memory.status not in {"tested", "benchmarked"} or not isinstance(memory.value, (int, float)):
                missing.append("gpu.usable_memory_gib")
            if missing:
                rejected.append(f"{report.node_id}: missing tested capabilities {sorted(set(missing))}")
                continue
            viable.append((float(memory.value), report.node_id, str(backend.value), dtype))
        if not viable:
            return HardwareResolution("blocked", None, None, None, tuple(rejected or ["no node reports supplied"]))
        _, node_id, backend, dtype = max(viable, key=lambda item: (item[0], item[1]))
        return HardwareResolution("selected", node_id, backend, dtype, tuple(rejected))

    @staticmethod
    def _dtype(facts: dict[str, Any]) -> str | None:
        for dtype in ("bf16", "fp16"):
            fact = facts.get(f"dtype.{dtype}")
            if fact is not None and fact.value is True and fact.status in {"tested", "benchmarked"}:
                return dtype
        return None
