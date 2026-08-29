from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from local_ai_lab.experiments.comparison import StrategyRun


@dataclass(frozen=True, slots=True)
class SelectionConstraints:
    privacy: str | None = None
    max_latency_ms: float | None = None
    max_cost: Decimal | None = None
    cost_currency: str = "USD"
    priorities: tuple[str, ...] = ("quality.fidelity", "retrieval.recall_at_k", "latency_ms")
    minimum_cases: int = 20
    require_formal_verdict: bool = True


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    status: str
    strategy_id: str | None
    explanation: tuple[str, ...]
    evidence_references: tuple[str, ...]
    uncertainty: str
    configuration_label: str | None = None
    configuration_fingerprint: str | None = None


class StrategySelector:
    """Evidence-gated, lexicographic selector; it never emits a probability as certainty."""

    def select(self, runs: Sequence[StrategyRun], constraints: SelectionConstraints) -> SelectionDecision:
        if not runs:
            return SelectionDecision("insufficient_evidence", None, ("no strategy runs supplied",), (), "No selection can be made.")
        comparable_cases = min(len(run.case_ids) for run in runs)
        if comparable_cases < constraints.minimum_cases:
            return SelectionDecision(
                "insufficient_evidence", None,
                (f"only {comparable_cases} comparable cases; {constraints.minimum_cases} required",),
                (), "The available sample is below the declared evidence threshold.",
            )
        eligible: list[StrategyRun] = []
        excluded: list[str] = []
        for run in runs:
            run.validate()
            reasons: list[str] = []
            if constraints.require_formal_verdict and run.formal_status != "model_drift_verified":
                reasons.append("no formal Model Drift verdict")
            if constraints.privacy and run.privacy != constraints.privacy:
                reasons.append("privacy constraint")
            if constraints.max_latency_ms is not None and run.latency_ms > constraints.max_latency_ms:
                reasons.append("latency constraint")
            if constraints.max_cost is not None:
                if run.cost_amount is None or run.cost_currency != constraints.cost_currency:
                    reasons.append("cost unknown or in a different currency")
                elif Decimal(run.cost_amount) > constraints.max_cost:
                    reasons.append("cost constraint")
            if reasons:
                excluded.append(f"{run.strategy_id}: {', '.join(reasons)}")
            else:
                eligible.append(run)
        if not eligible:
            return SelectionDecision(
                "no_eligible_strategy", None, tuple(excluded), (),
                "Constraints or verification requirements excluded every measured strategy.",
            )
        if not constraints.priorities or any(
            not (
                priority in {"latency_ms", "peak_memory_gib", "cost"}
                or priority.startswith("quality.")
                or priority.startswith("retrieval.")
                or priority.startswith("complexity.")
            )
            for priority in constraints.priorities
        ):
            raise ValueError("invalid selector priorities")
        chosen = sorted(eligible, key=lambda run: self._key(run, constraints.priorities))[0]
        explanation = [f"selected lexicographically by priorities: {', '.join(constraints.priorities)}"]
        explanation.extend(excluded)
        return SelectionDecision(
            "recommendation", chosen.strategy_id, tuple(explanation), chosen.evidence_references,
            "This is an evidence-bounded recommendation, not certainty; it must be revisited when the suite, snapshot, model or constraints change.",
            chosen.configuration_label, chosen.configuration_fingerprint,
        )

    @staticmethod
    def _key(run: StrategyRun, priorities: tuple[str, ...]) -> tuple:
        values = []
        for priority in priorities:
            if priority.startswith("quality."):
                values.append(-run.quality.get(priority.removeprefix("quality."), float("-inf")))
            elif priority.startswith("retrieval."):
                values.append(-run.retrieval.get(priority.removeprefix("retrieval."), float("-inf")))
            elif priority == "latency_ms":
                values.append(run.latency_ms)
            elif priority == "peak_memory_gib":
                values.append(run.peak_memory_gib if run.peak_memory_gib is not None else float("inf"))
            elif priority == "cost":
                values.append(Decimal(run.cost_amount) if run.cost_amount is not None else Decimal("Infinity"))
            elif priority.startswith("complexity."):
                values.append(run.complexity.get(priority.removeprefix("complexity."), float("inf")))
        return (*values, run.strategy_id)
