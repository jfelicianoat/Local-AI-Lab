from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from local_ai_lab.domain.common import sha256_json


@dataclass(frozen=True, slots=True)
class StrategyRun:
    strategy_run_id: str
    experiment_id: str
    strategy_id: str
    configuration_label: str
    configuration_fingerprint: str
    suite_fingerprint: str
    snapshot_hash: str
    case_ids: tuple[str, ...]
    model_fingerprint: str
    prompt_fingerprint: str
    retrieval_fingerprint: str | None
    node_id: str
    capability_report_hash: str
    quality: dict[str, float]
    retrieval: dict[str, float]
    latency_ms: float
    peak_memory_gib: float | None
    cost_amount: str | None
    cost_currency: str
    cost_source: str
    cost_verification_status: str
    privacy: str
    complexity: dict[str, float]
    formal_status: str
    evidence_references: tuple[str, ...]

    def validate(self) -> None:
        if self.cost_amount is None:
            if self.cost_verification_status != "unknown":
                raise ValueError("unknown cost must remain explicitly unknown")
        else:
            try:
                if Decimal(self.cost_amount) < 0:
                    raise ValueError("cost cannot be negative")
            except InvalidOperation as error:
                raise ValueError("cost amount must be a decimal string") from error
        if self.latency_ms < 0 or self.peak_memory_gib is not None and self.peak_memory_gib < 0:
            raise ValueError("latency and memory cannot be negative")
        if self.formal_status not in {"unverified", "local_verified", "model_drift_verified"}:
            raise ValueError("invalid formal verification status")


@dataclass(frozen=True, slots=True)
class StrategyComparison:
    experiment_id: str
    suite_fingerprint: str
    snapshot_hash: str
    dimensions: tuple[dict[str, Any], ...]
    caveats: tuple[str, ...]
    fingerprint: str


class StrategyComparator:
    def compare(self, runs: Sequence[StrategyRun]) -> StrategyComparison:
        if len(runs) < 2:
            raise ValueError("at least two strategy runs are required")
        for run in runs:
            run.validate()
        experiment_ids = {run.experiment_id for run in runs}
        suites = {run.suite_fingerprint for run in runs}
        snapshots = {run.snapshot_hash for run in runs}
        case_sets = {run.case_ids for run in runs}
        if len(experiment_ids) != 1 or len(suites) != 1 or len(snapshots) != 1 or len(case_sets) != 1:
            raise ValueError("strategy runs are not comparable on experiment, suite, snapshot and cases")
        dimensions: list[dict[str, Any]] = []
        for run in runs:
            dimensions.append(
                {
                    "strategy_id": run.strategy_id,
                    "configuration_label": run.configuration_label,
                    "configuration_fingerprint": run.configuration_fingerprint,
                    "quality": run.quality,
                    "retrieval": run.retrieval,
                    "cost": {
                        "amount": run.cost_amount,
                        "currency": run.cost_currency,
                        "source": run.cost_source,
                        "verification_status": run.cost_verification_status,
                    },
                    "latency_ms": run.latency_ms,
                    "peak_memory_gib": run.peak_memory_gib,
                    "privacy": run.privacy,
                    "complexity": run.complexity,
                    "formal_status": run.formal_status,
                    "evidence_references": list(run.evidence_references),
                }
            )
        caveats: list[str] = []
        if any(run.cost_amount is None for run in runs):
            caveats.append("one or more costs are unknown and were not converted to zero")
        if any(run.formal_status != "model_drift_verified" for run in runs):
            caveats.append("one or more strategies lack a formal Model Drift verdict")
        payload = {
            "experiment_id": next(iter(experiment_ids)),
            "suite_fingerprint": next(iter(suites)),
            "snapshot_hash": next(iter(snapshots)),
            "dimensions": dimensions,
            "caveats": caveats,
        }
        return StrategyComparison(
            payload["experiment_id"], payload["suite_fingerprint"], payload["snapshot_hash"],
            tuple(dimensions), tuple(caveats), sha256_json(payload),
        )
