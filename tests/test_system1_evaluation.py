from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai_lab.broker.client import BrokerHttpResponse, BrokerTaskClient
from local_ai_lab.domain.common import sha256_json
from local_ai_lab.evaluation.cascade import (
    LABELS, SemanticEvaluationConfig, SemanticEvaluator, evaluation_metrics,
)

MODEL = {"provider": "local", "deployment": "desktop", "model": "judge"}
CASE = {"case_id": "sample", "query": "Is the answer supported?", "gold_label": "correct"}


def judgment(**overrides):
    return {
        "use_case": "evaluation_semantic_label", "accepted": True, "decision": "correct",
        "confidence": 0.99, "confidence_is_calibrated": False, "provider": "laya_mcp",
        "model": "configured-by-broker", "latency_ms": 10.0,
        "fallback_used": False, "reason_code": None,
        "attempts": [{"provider": "laya_mcp", "tokens_input": 30, "tokens_output": 1}],
        **overrides,
    }


class Transport:
    def __init__(self, result=None, *, capabilities=None, fail=None, strong_label="correct", assistant_content=None):
        self.result = judgment() if result is None else result
        self.capabilities = {"system1_judgments": True} if capabilities is None else capabilities
        self.fail = fail
        self.strong_label = strong_label
        self.assistant_content = assistant_content
        self.calls = []

    def request(self, method, url, *, headers, body, timeout):
        payload = json.loads(body) if body else None
        self.calls.append((method, url, headers, payload, timeout))
        if url.endswith("/capabilities"):
            result = self.capabilities
        elif url.endswith("/system1/judge"):
            if isinstance(self.fail, Exception):
                raise self.fail
            if isinstance(self.fail, int):
                return BrokerHttpResponse(self.fail, b'{"detail":"unavailable"}')
            result = self.result
        elif url.endswith("/tasks"):
            self.target = payload["model_requirements"]["target_model"]
            result = {"task_id": "strong-task"}
        elif url.endswith("/invocations"):
            result = {"items": []}
        else:
            result = {"status": "completed", "result": {
                "assistant_content": self.assistant_content if self.assistant_content is not None else json.dumps({"label": self.strong_label}),
                "model_used": self.target, "usage": {},
            }}
        return BrokerHttpResponse(200, json.dumps(result).encode())


def evaluator(transport=None, **config):
    transport = transport or Transport()
    client = BrokerTaskClient(endpoint="http://127.0.0.1:8000", token="private-token", transport=transport, poll_interval=0)
    return SemanticEvaluator(client, SemanticEvaluationConfig(
        **{"enabled": True, "shadow_mode": False, "strong_judge_model": MODEL, **config},
    ))


def evaluate(engine, **changes):
    arguments = {
        "case": CASE, "response": "A supported answer.", "verification": None,
        "evidence": [], "correlation_id": "correlation", **changes,
    }
    arguments["case"] = {**arguments["case"], "gold_response_sha256": arguments["case"].get("gold_response_sha256", sha256_json(arguments["response"]))}
    return engine.evaluate(**arguments)


def test_synchronous_judge_contract_auth_privacy_and_capability_cache():
    transport = Transport()
    engine = evaluator(transport)
    assert evaluate(engine)["origin"] == "system1"
    assert evaluate(engine)["label"] == "correct"
    assert len([c for c in transport.calls if c[1].endswith("/capabilities")]) == 1
    calls = [c for c in transport.calls if c[0] == "POST"]
    assert len(calls) == 2
    for _, url, headers, body, timeout in calls:
        assert url.endswith("/api/v1/system1/judge")
        assert headers["X-Admin-Token"] == "private-token"
        assert body["cloud_allowed"] is False
        assert body["use_case"] == "evaluation_semantic_label"
        assert body["decision_type"] == "choice"
        assert body["options"] == list(LABELS)
        assert set(body["criteria"]) == set(LABELS)
        assert set(body) == {"use_case", "input", "decision_type", "options", "criteria", "instructions", "cloud_allowed"}
        assert timeout == 75


def test_october_extension_explicitly_requests_default_profile_for_custom_use_case():
    transport = Transport(capabilities={"system1_judgments": True, "system1_evaluation": True})
    assert evaluate(evaluator(transport))["origin"] == "system1"
    body = next(c[3] for c in transport.calls if c[1].endswith("/system1/judge"))
    assert body["threshold_profile"] == "default"
    assert "target" not in body


def test_target_requires_capability_and_preserves_returned_canonical_model():
    transport = Transport(judgment(provider="laya_mcp", model="convaiinnovations/laya/multilingual"),
                          capabilities={"system1_judgments": True, "system1_evaluation": True})
    result = evaluate(evaluator(transport, system1_target={"provider": "laya_mcp", "model": "multilingual"}))
    body = next(c[3] for c in transport.calls if c[1].endswith("/system1/judge"))
    assert body["target"] == {"provider": "laya_mcp", "model": "multilingual"}
    assert result["system1"]["model"] == "convaiinnovations/laya/multilingual"
    old = Transport()
    result = evaluate(evaluator(old, system1_target={"provider": "laya_mcp"}))
    assert result["reason_code"] == "SYSTEM1_TARGET_UNAVAILABLE"
    assert not any(c[1].endswith("/system1/judge") for c in old.calls)


def test_pinned_target_cannot_attribute_other_provider_result_to_requested_model():
    transport = Transport(judgment(provider="ollama_system1"),
                          capabilities={"system1_judgments": True, "system1_evaluation": True})
    result = evaluate(evaluator(transport, system1_target={"provider": "laya_mcp"}))
    assert result["origin"] == "strong_judge" and result["reason_code"] == "INVALID_OUTPUT"


@pytest.mark.parametrize("reason,source,score", [("LOW_CONFIDENCE", "native", 0.6), ("SELF_REPORTED_SCORE", "self_reported", 1.0)])
def test_raw_rejected_attempts_are_measured_and_never_used_for_acceptance(reason, source, score):
    attempt = {"provider": "ollama_system1", "model": "specific-model", "decision": "correct",
               "confidence": score, "alternatives": [{"value": "incorrect", "confidence": 1 - score}],
               "score_source": source, "reason_code": reason}
    result = evaluate(evaluator(Transport(judgment(accepted=False, decision=None, confidence=None, reason_code=reason, attempts=[attempt]))))
    assert result["origin"] == "strong_judge"
    assert result["reason_code"] == reason
    assert result["system1"]["attempts"][0]["decision"] == "correct"
    assert result["system1"]["attempts"][0]["score_source"] == source
    group = evaluation_metrics([{"evaluation": result}])["system1_attempts"][0]
    assert group["rejected_scores"] == 1
    assert group["gold"]["agreement"] == 1
    assert sum(bin["count"] for bin in group["confidence_bins"]) == (1 if source == "native" else 0)


def test_self_reported_attempt_cannot_autoaccept_even_with_invalid_accepted_flag():
    result = evaluate(evaluator(Transport(judgment(attempts=[{
        "provider": "ollama_system1", "model": "teacher", "decision": "correct", "confidence": 1.0,
        "score_source": "self_reported", "reason_code": None,
    }]))))
    assert result["origin"] == "strong_judge"
    assert result["reason_code"] == "INVALID_OUTPUT"


@pytest.mark.parametrize("case,response,expected", [
    ({"evaluator": {"type": "exact_match", "expected": "yes"}}, "yes", "correct"),
    ({"evaluator": {"type": "exact_match", "expected": "yes"}}, "no", "incorrect"),
    ({"evaluator": {"type": "regex", "pattern": "[A-Z]{2}"}}, "AB", "correct"),
    ({"evaluator": {"type": "regex", "pattern": "[A-Z]{2}"}}, "ABC", "incorrect"),
    ({"evaluator": {"type": "numeric", "expected": 5, "tolerance": 0.1}}, "5.05", "correct"),
    ({"evaluator": {"type": "numeric", "expected": 5}}, "nan", "incorrect"),
    ({"evaluator": {"type": "json_schema", "schema": {"type": "object", "required": ["answer"]}}}, {"answer": "a"}, "correct"),
])
def test_deterministic_evaluators_never_call_models(case, response, expected):
    transport = Transport()
    result = evaluate(evaluator(transport), case={**CASE, **case}, response=response)
    assert result["origin"] == "deterministic"
    assert result["label"] == expected
    assert transport.calls == []


def test_existing_mandatory_verification_failure_cannot_be_overridden():
    transport = Transport()
    result = evaluate(evaluator(transport), verification={"deterministic_pass": False})
    assert result["label"] == "incorrect"
    assert result["reason_code"] == "DETERMINISTIC_FAILED"
    assert transport.calls == []


@pytest.mark.parametrize("score,origin", [(0.95, "system1"), (0.949, "strong_judge"), (0.8, "strong_judge")])
def test_threshold_and_strong_judge_reuse_existing_task_client(score, origin):
    transport = Transport(judgment(confidence=score))
    result = evaluate(evaluator(transport))
    assert result["origin"] == origin
    assert result["escalated"] == (origin == "strong_judge")
    tasks = [c for c in transport.calls if c[1].endswith("/tasks")]
    if origin == "strong_judge":
        assert tasks[0][3]["model_requirements"] == {"target_model": MODEL, "fallback_allowed": False}
        assert tasks[0][3]["risk"]["data_classification"] == "local_only"
        assert tasks[0][3]["exclude_from_model_learning"] is True
        assert result["strong_judge"]["cost_amount"] is None
    else:
        assert tasks == []


def test_evaluator_specific_threshold_changes_escalation():
    transport = Transport(judgment(confidence=0.96))
    result = evaluate(evaluator(transport, thresholds={"strict": 0.98}), case={**CASE, "evaluator": {"id": "strict", "type": "semantic"}})
    assert result["origin"] == "strong_judge"
    assert result["threshold"] == 0.98


@pytest.mark.parametrize("failure", [503, 401, TimeoutError(), OSError("offline")])
def test_broker_failure_always_falls_back(failure):
    result = evaluate(evaluator(Transport(fail=failure)))
    assert result["origin"] == "strong_judge"
    assert result["reason_code"] == "BROKER_ERROR"


@pytest.mark.parametrize("overrides", [
    {"accepted": False, "decision": None, "confidence": None, "reason_code": "FUTURE_REASON"},
    {"accepted": "true"}, {"decision": "unknown"}, {"decision": False},
    {"confidence": True}, {"confidence": float("nan")}, {"confidence": 1.1},
    {"use_case": "different"}, {"provider": None}, {"attempts": {}},
])
def test_rejected_or_invalid_response_never_autoaccepts(overrides):
    result = evaluate(evaluator(Transport(judgment(**overrides))))
    assert result["origin"] == "strong_judge"


def test_broker_can_fallback_from_laya_to_ollama_without_client_provider_selection():
    result = evaluate(evaluator(Transport(judgment(
        provider="ollama_system1", fallback_used=True, reason_code="MCP_ERROR",
        attempts=[{"provider": "laya_mcp", "reason_code": "MCP_ERROR"},
                  {"provider": "ollama_system1", "reason_code": None}],
    ))))
    assert result["origin"] == "system1"
    assert result["provider"] == "ollama_system1"
    assert result["reason_code"] == "MCP_ERROR"
    assert result["system1"]["tokens"]["tokens_input"] is None


def test_old_broker_capability_is_false_and_does_not_post_to_missing_route():
    transport = Transport(capabilities={"contract_version": "2.10"})
    result = evaluate(evaluator(transport))
    assert result["origin"] == "strong_judge"
    assert not any(c[1].endswith("/system1/judge") for c in transport.calls)


def test_shadow_mode_keeps_judge_label_and_records_disagreement():
    transport = Transport(strong_label="incorrect")
    engine = evaluator(transport, shadow_mode=True)
    result = evaluate(engine)
    assert result["label"] == "incorrect"
    assert result["origin"] == "strong_judge"
    assert result["system1"]["decision"] == "correct"
    metrics = evaluation_metrics([{"evaluation": result}])
    assert metrics["shadow_vs_strong_judge"]["agreement"] == 0
    assert metrics["gold"]["agreement"] == 0
    assert metrics["system1_eligible_gold"]["agreement"] == 1


def test_require_calibration_escalates_uncalibrated_scores():
    result = evaluate(evaluator(require_calibrated=True))
    assert result["origin"] == "strong_judge"
    assert result["reason_code"] == "UNCALIBRATED_SCORE"


def test_no_strong_judge_or_invalid_strong_output_keeps_previous_review():
    engine = evaluator(Transport(judgment(confidence=0.6)), strong_judge_model=None)
    result = evaluate(engine)
    assert result["label"] is None and result["needs_review"] is True
    assert result["origin"] == "previous_flow"
    assert result["fallback_reason"] == "STRONG_JUDGE_NOT_CONFIGURED"
    result = evaluate(evaluator(Transport(judgment(confidence=0.6), strong_label="invented")))
    assert result["label"] is None and result["fallback_reason"] == "STRONG_JUDGE_ERROR"


def test_feature_off_has_no_added_result_and_no_calls():
    transport = Transport()
    engine = evaluator(transport, enabled=False)
    assert evaluate(engine) is None
    assert transport.calls == []


def test_configuration_and_frozen_input_reexecution_match_decisions():
    a, b = evaluate(evaluator()), evaluate(evaluator())
    assert a["label"] == b["label"]
    assert a["origin"] == b["origin"]
    assert a["configuration_fingerprint"] == b["configuration_fingerprint"]
    assert a["system1"] == b["system1"]


def test_gold_label_for_another_response_is_excluded_from_quality_metrics():
    result = evaluate(evaluator(), case={**CASE, "gold_response_sha256": sha256_json("different response")})
    assert result["gold_label"] is None
    metrics = evaluation_metrics([{"evaluation": result}])
    assert metrics["gold"]["compared"] == 0
    assert metrics["gold"]["agreement"] is None
    assert metrics["gold_response_mismatches"] == 1


@pytest.mark.parametrize("config", [{"threshold": float("nan")}, {"threshold": 1.1},
                                     {"enabled": "false"}, {"strong_judge_model": {"model": "a"}},
                                     {"thresholds": {"semantic": -0.1}}, {"unknown": True}])
def test_invalid_configuration_fails_before_inference(config):
    with pytest.raises(ValueError):
        SemanticEvaluationConfig.model_validate(config)


def test_120_case_mock_batch_routes_and_measures_gold_without_claiming_real_accuracy(tmp_path: Path):
    rows = []
    for index in range(120):
        expected = LABELS[index % 3]
        transport = Transport(judgment(decision=expected, confidence=0.99 if index < 80 else 0.7), strong_label=expected)
        case = {**CASE, "case_id": f"mock-{index}", "query": f"Mock query {index}", "gold_label": expected}
        response = f"Mock response {index}"
        if index < 40:
            case.update(evaluator={"type": "exact_match", "expected": response}, gold_label="correct")
        rows.append({"case_id": case["case_id"], "evaluation": evaluate(evaluator(transport), case=case, response=response)})
    metrics = evaluation_metrics(rows)
    assert metrics["total"] == 120
    assert metrics["origins"] == {"deterministic": 40, "system1": 40, "strong_judge": 40, "previous_flow": 0}
    assert metrics["escalation_rate"] == pytest.approx(1 / 3)
    assert metrics["gold"]["agreement"] == 1
    assert metrics["system1_eligible_gold"]["compared"] == 40
    assert metrics["system1_cost_amount"] is None
    (tmp_path / "mock-benchmark.json").write_text(json.dumps({"mode": "mock_contract_test", "metrics": metrics, "results": rows}), encoding="utf-8")
