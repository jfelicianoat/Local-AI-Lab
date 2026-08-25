from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from local_ai_lab.experiments.comparison import StrategyComparator, StrategyRun
from local_ai_lab.experiments.selector import SelectionConstraints, StrategySelector


def _run(
    strategy: str,
    *,
    fidelity: float,
    recall: float,
    latency: float,
    cost: str | None = "0.10",
    formal: str = "model_drift_verified",
    cases: int = 24,
) -> StrategyRun:
    return StrategyRun(
        strategy_run_id=f"run-{strategy}", experiment_id="exp-1", strategy_id=strategy,
        suite_fingerprint="a" * 64, snapshot_hash="b" * 64,
        case_ids=tuple(f"case-{index}" for index in range(cases)),
        model_fingerprint=f"model-{strategy}", prompt_fingerprint="prompt-1",
        retrieval_fingerprint=f"retrieval-{strategy}" if strategy != "F1" else None,
        node_id="node-1", capability_report_hash="c" * 64,
        quality={"fidelity": fidelity, "completeness": fidelity - 0.05},
        retrieval={"recall_at_k": recall}, latency_ms=latency, peak_memory_gib=8.0,
        cost_amount=cost, cost_currency="USD", cost_source="measured" if cost else "not_available",
        cost_verification_status="verified" if cost else "unknown", privacy="local_only",
        complexity={"manual_steps": 2.0 if strategy == "F2" else 1.0}, formal_status=formal,
        evidence_references=(f"artifact:sha256:{strategy}",),
    )


def test_f1_f2_and_best_rag_are_compared_without_global_score() -> None:
    comparison = StrategyComparator().compare(
        [_run("F1", fidelity=0.80, recall=0.0, latency=120),
         _run("F2", fidelity=0.91, recall=0.90, latency=180),
         _run("R4", fidelity=0.89, recall=0.94, latency=150, cost=None)]
    )

    assert len(comparison.dimensions) == 3
    assert all("score" not in row for row in comparison.dimensions)
    assert all(set(row) >= {"quality", "retrieval", "cost", "latency_ms", "peak_memory_gib", "privacy", "complexity"} for row in comparison.dimensions)
    assert any("unknown" in caveat for caveat in comparison.caveats)


def test_noncomparable_strategy_runs_are_rejected() -> None:
    first = _run("R3", fidelity=0.8, recall=0.8, latency=100)
    second = replace(_run("R4", fidelity=0.9, recall=0.9, latency=110), snapshot_hash="d" * 64)

    with pytest.raises(ValueError, match="not comparable"):
        StrategyComparator().compare([first, second])


def test_selector_refuses_small_or_unverified_evidence() -> None:
    small = [_run("R3", fidelity=0.8, recall=0.8, latency=100, cases=5)]
    decision = StrategySelector().select(small, SelectionConstraints(minimum_cases=20))
    assert decision.status == "insufficient_evidence"
    unverified = [_run("R3", fidelity=0.8, recall=0.8, latency=100, formal="local_verified")]
    decision = StrategySelector().select(unverified, SelectionConstraints())
    assert decision.status == "no_eligible_strategy"


def test_selector_uses_declared_metrics_and_explains_uncertainty() -> None:
    runs = [
        _run("R3", fidelity=0.90, recall=0.86, latency=100, cost="0.05"),
        _run("R4", fidelity=0.92, recall=0.95, latency=150, cost="0.08"),
    ]
    constraints = SelectionConstraints(
        privacy="local_only", max_latency_ms=200, max_cost=Decimal("0.10"),
        priorities=("quality.fidelity", "retrieval.recall_at_k", "latency_ms"),
    )
    decision = StrategySelector().select(runs, constraints)

    assert decision.status == "recommendation"
    assert decision.strategy_id == "R4"
    assert "not certainty" in decision.uncertainty
    assert decision.evidence_references
