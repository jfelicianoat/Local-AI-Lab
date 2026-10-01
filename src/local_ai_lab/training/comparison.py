"""Measured deterministic verification for a comparable strategy suite."""
from __future__ import annotations

import math
from typing import Any


def require_same_task(
    *, strategy_id: str, training: dict[str, Any], baseline: dict[str, Any],
    execution: dict[str, Any], benchmark_id: str | None, index_id: str | None,
    embedding_model: str | None, embedding_model_fingerprint: str | None,
    k: int, expected_baseline_model: str | None,
) -> None:
    baseline_strategy = {"F1": "B1", "F2": "R4"}.get(strategy_id)
    if baseline_strategy is None or training.get("evaluation_strategy_id") != strategy_id or baseline.get("strategy_id") != baseline_strategy:
        raise ValueError("trained model must be evaluated as F1 against B1 or F2 against R4")
    if any(baseline.get(key) != execution.get(key) for key in (
        "suite_fingerprint", "snapshot_hash", "snapshot_id", "case_ids"
    )) or baseline.get("benchmark_id") != benchmark_id:
        raise ValueError("trained model evaluation must reuse the baseline's exact task and cases")
    if (baseline.get("index_id") != index_id or baseline.get("k") != k
            or (strategy_id == "F2" and any(baseline.get(key) != value for key, value in (
                ("embedding_model", embedding_model),
                ("embedding_model_fingerprint", embedding_model_fingerprint),
            )))):
        raise ValueError("trained model evaluation must reuse the baseline's retrieval configuration")
    target = baseline.get("target_model")
    if not isinstance(target, dict) or target.get("model") != expected_baseline_model:
        raise ValueError("baseline model must match the training base or distillation teacher")
    if (training.get("baseline_suite_fingerprint") != baseline["suite_fingerprint"]
            or training.get("baseline_snapshot_hash") != baseline["snapshot_hash"]
            or training.get("baseline_case_ids") != baseline["case_ids"]):
        raise ValueError("training baseline evidence changed since approval")


def verified_pass_rate(report: dict[str, Any], case_ids: list[str]) -> float:
    if report.get("schema_version") != "strategy-suite-report.v1" or not case_ids:
        raise ValueError("strategy report has no complete measured suite")
    results = report.get("results")
    if not isinstance(results, list) or [item.get("case_id") if isinstance(item, dict) else None
                                             for item in results] != case_ids:
        raise ValueError("strategy report results differ from the selected cases")
    passed = 0
    for item in results:
        verification = item.get("verification")
        if verification is None:
            continue
        if not isinstance(verification, dict) or type(verification.get("deterministic_pass")) is not bool:
            raise ValueError("strategy report has invalid per-case verification")
        passed += verification["deterministic_pass"]
    measured = passed / len(case_ids)
    quality = report.get("quality")
    reported = quality.get("deterministic_pass_rate") if isinstance(quality, dict) else None
    if (type(reported) not in {int, float} or not math.isfinite(reported)
            or not math.isclose(measured, reported, rel_tol=0, abs_tol=1e-9)):
        raise ValueError("strategy report pass rate differs from its case results")
    latency = report.get("latency_ms")
    if type(latency) not in {int, float} or not math.isfinite(latency) or latency < 0:
        raise ValueError("strategy report lacks measured latency")
    return measured


def compare_verification_gain(baseline: float, observed: float, minimum_gain: float) -> dict[str, Any]:
    if any(type(value) not in {int, float} or not math.isfinite(value)
           for value in (baseline, observed, minimum_gain)):
        raise ValueError("verification comparison requires finite measurements")
    if not 0 <= baseline <= 1 or not 0 <= observed <= 1 or not 0 < minimum_gain <= 1:
        raise ValueError("verification comparison is outside its measured range")
    gain = observed - baseline
    return {
        "metric": "deterministic_pass_rate",
        "baseline": baseline,
        "observed": observed,
        "gain": gain,
        "minimum_gain": minimum_gain,
        "target_met": gain + 1e-9 >= minimum_gain,
        "scope": "format_and_citation_checks_not_answer_fidelity",
    }
