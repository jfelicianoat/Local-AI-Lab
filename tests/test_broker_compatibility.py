from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai_lab.broker.compatibility import (
    ALLOWED_PATHS,
    BrokerCompatibilityChecker,
    ReadOnlyResponse,
    normalize_broker_endpoint,
)


CAPABILITIES_29 = {
    "contract_version": "2.9",
    "strategies": ["single", "mixture_of_agents", "agent"],
    "exact_target_model": True,
    "derived_data_boundary": True,
    "generation_determinism": True,
    "exclude_from_model_learning": True,
    "invocation_telemetry": True,
    "execution_fingerprint": True,
    "client_tool_passthrough": True,
}


class FakeTransport:
    def __init__(self, responses: dict[str, ReadOnlyResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> ReadOnlyResponse:
        self.calls.append((url, dict(headers), timeout))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def encoded(payload: object, status: int = 200) -> ReadOnlyResponse:
    return ReadOnlyResponse(status, json.dumps(payload).encode())


def checker_for(capabilities: object, health: object | None = None) -> tuple[BrokerCompatibilityChecker, FakeTransport]:
    base = "http://127.0.0.1:8765"
    transport = FakeTransport(
        {
            base + "/health": encoded({"status": "ok"} if health is None else health),
            base + "/api/v1/capabilities": encoded(capabilities),
        }
    )
    return BrokerCompatibilityChecker(transport), transport


def test_formal_evaluation_is_satisfied_by_29() -> None:
    checker, transport = checker_for(CAPABILITIES_29)

    report = checker.check(endpoint="http://127.0.0.1:8765/", phase="formal_evaluation")

    assert report.status == "satisfied"
    assert report.observed_contract == "2.9"
    assert report.missing_capabilities == []
    assert report.upgrade_required is False
    assert {call[0].removeprefix("http://127.0.0.1:8765") for call in transport.calls} == set(ALLOWED_PATHS)


def test_old_contract_and_missing_flags_require_upgrade() -> None:
    checker, _ = checker_for(
        {"contract_version": "2.8", "strategies": ["single"], "exact_target_model": True}
    )

    report = checker.check(endpoint="http://127.0.0.1:8765", phase="formal_evaluation")

    assert report.status == "unsatisfied"
    assert report.upgrade_required is True
    assert "generation_determinism" in report.missing_capabilities


def test_additive_unknown_fields_are_tolerated() -> None:
    capabilities = dict(CAPABILITIES_29, future_contract_field={"anything": True})
    checker, _ = checker_for(capabilities)

    report = checker.check(endpoint="http://127.0.0.1:8765", phase="formal_evaluation")

    assert report.status == "satisfied"


@pytest.mark.parametrize("status,kind", [(401, "authentication"), (403, "authentication"), (429, "transient"), (503, "transient"), (404, "permanent")])
def test_http_failures_are_classified_without_claiming_upgrade(status: int, kind: str) -> None:
    base = "http://localhost:8765"
    transport = FakeTransport(
        {
            base + "/health": encoded({"status": "ok"}),
            base + "/api/v1/capabilities": ReadOnlyResponse(status, b"{}"),
        }
    )

    report = BrokerCompatibilityChecker(transport).check(endpoint=base, phase="phase0")

    assert report.status == "unknown"
    assert report.upgrade_required is False
    assert report.errors[-1].kind == kind


def test_invalid_contract_is_unknown_not_incompatible() -> None:
    checker, _ = checker_for({"strategies": []})

    report = checker.check(endpoint="http://127.0.0.1:8765", phase="phase0")

    assert report.status == "unknown"
    assert report.errors[-1].kind == "contract"


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///tmp/broker",
        "http://user:secret@localhost:8765",
        "http://localhost:8765/api/v1",
        "http://localhost:8765?token=secret",
        "http://localhost:8765#fragment",
    ],
)
def test_unsafe_endpoint_is_rejected(endpoint: str) -> None:
    with pytest.raises(ValueError):
        normalize_broker_endpoint(endpoint)


def test_transport_contract_exposes_get_only_and_token_is_not_reported() -> None:
    checker, transport = checker_for(CAPABILITIES_29)

    report = checker.check(
        endpoint="http://127.0.0.1:8765", phase="phase0", token="very-secret"
    )

    assert not hasattr(transport, "post")
    assert all(call[1]["X-Admin-Token"] == "very-secret" for call in transport.calls)
    assert "very-secret" not in report.to_json()


def test_requirement_artifact_matches_executable_policy() -> None:
    artifact = json.loads(
        Path("artifacts/phase0/broker-requirements.v1.json").read_text(encoding="utf-8")
    )

    assert artifact["policy"]["allowed_methods"] == ["GET"]
    assert tuple(artifact["policy"]["allowed_paths"]) == ALLOWED_PATHS
    assert artifact["requirement_sets"]["formal_evaluation"]["minimum_contract"] == "2.9"
