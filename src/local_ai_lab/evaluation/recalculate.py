"""Recalculate labels over stored strategy responses without regenerating them."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from local_ai_lab.benchmark.execution import load_execution_suite
from local_ai_lab.broker.client import BrokerTaskClient
from local_ai_lab.domain.common import sha256_json
from local_ai_lab.evaluation.cascade import (
    SemanticEvaluationConfig, SemanticEvaluator, evaluation_metrics, validate_case_evaluator,
)
from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier


def evaluation_evidence(case, response, verifier, retrieved_context) -> list[dict[str, Any]]:
    chunk_ids = {item["chunk_id"] for item in retrieved_context
                 if isinstance(item, dict) and isinstance(item.get("chunk_id"), str)}
    if isinstance(response, dict):
        for category in ("findings", "contradictions"):
            for claim in response.get(category, []) if isinstance(response.get(category), list) else []:
                if isinstance(claim, dict) and isinstance(claim.get("evidence"), list):
                    chunk_ids.update(ref["chunk_id"] for ref in claim["evidence"]
                                     if isinstance(ref, dict) and isinstance(ref.get("chunk_id"), str))
    reference = case.get("reference_answer")
    if isinstance(reference, dict):
        chunk_ids.update(ref["chunk_id"] for ref in reference.get("evidence", [])
                         if isinstance(ref, dict) and isinstance(ref.get("chunk_id"), str))
    return [{"chunk_id": cid, "content": verifier.chunks[cid]["content"]}
            for cid in sorted(chunk_ids) if cid in verifier.chunks]


def recalculate_strategy_report(
    *, report_path: Path, suite_root: Path, snapshot: Path, client: BrokerTaskClient,
    config: SemanticEvaluationConfig, gold_labels: dict[str, dict[str, Any]] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    if not config.enabled:
        raise ValueError("reevaluation requires enabled evaluation")
    if limit is not None and limit < 1:
        raise ValueError("reevaluation limit must be positive")
    raw = report_path.read_bytes()
    report = json.loads(raw)
    suite = load_execution_suite(suite_root, snapshot)
    verifier = ResearchResponseVerifier(snapshot)
    if (report.get("schema_version") != "strategy-suite-report.v1"
            or report.get("suite_fingerprint") != suite.fingerprint
            or report.get("snapshot_hash") != verifier.snapshot_hash):
        raise ValueError("reevaluation requires the report's exact frozen suite and snapshot")
    ids = [case["case_id"] for case in suite.cases]
    if report.get("case_ids") != ids or [row.get("case_id") for row in report.get("results", [])] != ids:
        raise ValueError("reevaluation report cases differ from the frozen suite")
    gold_labels = gold_labels or {}
    if not isinstance(gold_labels, dict) or not set(gold_labels) <= set(ids):
        raise ValueError("gold labels reference unknown cases")
    cases = []
    for case in suite.cases:
        gold = gold_labels.get(case["case_id"], {})
        if not isinstance(gold, dict) or set(gold) - {"label", "response_sha256"}:
            raise ValueError("gold entries require label and response_sha256")
        frozen_case = {**case, **({"gold_label": gold.get("label"), "gold_response_sha256": gold.get("response_sha256")} if gold else {})}
        validate_case_evaluator(frozen_case)
        cases.append(frozen_case)
    candidates = {row["case_id"]: row for row in report.get("review_candidates", [])}
    evaluator = SemanticEvaluator(client, config)
    source_hash = hashlib.sha256(raw).hexdigest()
    results = []
    for case, row in list(zip(cases, report["results"], strict=True))[:limit]:
        response = row.get("response") if row.get("response") is not None else row.get("raw_response")
        started = time.monotonic()
        verification = verifier.verify(response).as_dict() if (
            isinstance(response, dict) or report.get("strategy_id") != "B0"
        ) else None
        deterministic_latency = (time.monotonic() - started) * 1000
        evidence = evaluation_evidence(case, response, verifier, candidates.get(case["case_id"], {}).get("retrieved_context", []))
        evaluation = evaluator.evaluate(
            case=case, response=response, verification=verification, evidence=evidence,
            correlation_id=f"reevaluate:{source_hash[:16]}:{case['case_id']}",
        )
        evaluation["stage_latency_ms"]["deterministic"] += deterministic_latency
        results.append({"case_id": case["case_id"], "response_sha256": sha256_json(response), "evaluation": evaluation})
    return {
        "schema_version": "semantic-reevaluation-report.v1", "source_report_sha256": source_hash,
        "suite_fingerprint": suite.fingerprint, "snapshot_hash": verifier.snapshot_hash,
        "case_ids": [row["case_id"] for row in results], "evaluation": config.model_dump(),
        "evaluation_configuration_fingerprint": evaluator.configuration_fingerprint,
        "evaluation_metrics": evaluation_metrics(results), "results": results,
        "formal_status": "unverified", "stability": None,
    }
