from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from local_ai_lab.broker.client import BrokerHttpResponse, BrokerInvocationError, BrokerTaskClient
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter
from local_ai_lab.retrieval.engine import RetrievalCandidate
from local_ai_lab.strategies.generation import B0Strategy, RagStrategy


class FakeBrokerTransport:
    def __init__(self, assistant_content: str, *, fallback: bool = False, usage=None) -> None:
        self.assistant_content = assistant_content
        self.fallback = fallback
        self.usage = usage or {}
        self.calls = []

    def request(self, method, url, *, headers, body, timeout):
        payload = json.loads(body) if body else None
        self.calls.append((method, url, headers, payload))
        if method == "POST":
            return BrokerHttpResponse(200, b'{"task_id":"task-1"}')
        if url.endswith("/invocations"):
            return BrokerHttpResponse(200, b'{"items":[{"invocation_id":"i-1"}]}')
        state = {
            "task_id": "task-1", "status": "succeeded",
            "assistant_content": self.assistant_content,
            "model_used": {"provider": "local", "deployment": "desktop", "model": "test"},
            "fallback_used": self.fallback, "usage": self.usage,
        }
        return BrokerHttpResponse(200, json.dumps(state).encode())


def _client(transport: FakeBrokerTransport) -> BrokerTaskClient:
    return BrokerTaskClient(
        endpoint="http://127.0.0.1:8765", token="secret", transport=transport,
        poll_interval=0, max_wait=1,
    )


def test_b0_uses_broker_exact_target_without_fallback_or_learning() -> None:
    transport = FakeBrokerTransport("plain response")
    execution = B0Strategy(_client(transport)).execute(
        query="Hello", target_model={"provider": "local", "deployment": "desktop", "model": "test"},
        correlation_id="corr-1",
    )

    submitted = transport.calls[0][3]
    assert execution.raw_response == "plain response"
    assert submitted["model_requirements"]["fallback_allowed"] is False
    assert submitted["exclude_from_model_learning"] is True
    assert submitted["content"]["metadata"]["correlation_id"] == "corr-1"
    assert "secret" not in json.dumps(submitted)


def test_broker_rejects_declared_fallback_and_keeps_unknown_cost_unknown() -> None:
    with pytest.raises(BrokerInvocationError, match="fallback"):
        B0Strategy(_client(FakeBrokerTransport("response", fallback=True))).execute(
            query="Hello", target_model={"provider": "local", "deployment": "desktop", "model": "test"},
            correlation_id="corr-1",
        )
    execution = B0Strategy(_client(FakeBrokerTransport("response", usage={}))).execute(
        query="Hello", target_model={"provider": "local", "deployment": "desktop", "model": "test"},
        correlation_id="corr-2",
    )
    assert execution.broker.cost_amount is None
    assert execution.broker.cost_verification_status == "unknown"


def test_broker_29_nested_result_completes_client_tool_loop() -> None:
    class Broker29Transport:
        def __init__(self) -> None:
            self.calls = []
            self.poll_count = 0

        def request(self, method, url, *, headers, body, timeout):
            payload = json.loads(body) if body else None
            self.calls.append((method, url, headers, payload))
            if method == "POST" and url.endswith("/api/v1/tasks"):
                return BrokerHttpResponse(202, b'{"task_id":"task-29"}')
            if method == "POST" and url.endswith("/tool_results"):
                return BrokerHttpResponse(202, b'{"accepted":true}')
            if url.endswith("/invocations"):
                return BrokerHttpResponse(200, b'{"items":[{"invocation_id":"i-29"}]}')
            self.poll_count += 1
            if self.poll_count == 1:
                state = {
                    "task_id": "task-29", "status": "waiting_for_tools",
                    "result": {"pending_tool_calls": [{
                        "tool_call_id": "tool-1", "name": "retrieve_private_evidence",
                        "arguments": {"query": "Atlas"},
                    }]},
                }
            else:
                state = {
                    "task_id": "task-29", "status": "completed",
                    "execution_summary": {
                        "fallback_used": False,
                        "served_by": {"provider": "local", "deployment": "desktop", "model": "test"},
                    },
                    "result": {
                        "assistant_content": "grounded response",
                        "usage": {"cost_actual_usd": "0.002"},
                    },
                }
            return BrokerHttpResponse(200, json.dumps(state).encode())

    transport = Broker29Transport()
    client = _client(transport)  # type: ignore[arg-type]
    invocation = client.invoke(
        prompt="Consulta", target_model={"provider": "local", "deployment": "desktop", "model": "test"},
        generation={"temperature": 0}, json_schema=None, correlation_id="corr-29",
        execution={"strategy": "agent", "preset": "balanced", "timeout_seconds": 180},
        client_tool_handler=lambda call: json.dumps({"query": call["arguments"]["query"], "hits": []}),
    )

    submitted = transport.calls[0][3]
    tool_submission = next(call[3] for call in transport.calls if call[1].endswith("/tool_results"))
    assert submitted["idempotency_key"] == "lal:corr-29"
    assert submitted["risk"]["data_classification"] == "local_only"
    assert tool_submission["tool_results"][0]["tool_call_id"] == "tool-1"
    assert invocation.text == "grounded response"
    assert invocation.model_used["model"] == "test"
    assert invocation.cost_amount == "0.002"
    assert invocation.cost_verification_status == "verified"


def test_rag_strategy_sends_exact_context_and_verifies_returned_evidence(tmp_path: Path) -> None:
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Atlas.md").write_text("# Owner\nAna Torres dirige Atlas.", encoding="utf-8")
    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=allowed, vault_root=vault),
        tmp_path / "snapshots", vault_id=str(uuid.uuid4()),
    )
    note = json.loads((snapshot.path / "notes.jsonl").read_text(encoding="utf-8"))
    chunk = json.loads((snapshot.path / "chunks.jsonl").read_text(encoding="utf-8"))
    source = f"snapshot:sha256:{snapshot.global_hash}#chunk:{chunk['chunk_id']}"
    response = {
        "answer": "Ana Torres dirige Atlas.",
        "findings": [{"claim": "Ana Torres dirige Atlas.", "evidence": [{
            "snapshot_id": snapshot.snapshot_id, "note_id": note["note_id"],
            "note_path": note["relative_path"], "section": chunk["section"],
            "chunk_id": chunk["chunk_id"], "source_reference": source,
        }]}],
        "contradictions": [], "uncertainties": [], "missing_information": [],
    }

    class StaticRetriever:
        strategy_id = "R3.hybrid-rrf.v1"

        def retrieve(self, query, *, limit=10):
            return [RetrievalCandidate(
                chunk["chunk_id"], note["note_id"], note["relative_path"], chunk["section"],
                chunk["content"], 1.0, 1, self.strategy_id, source,
            )]

    schema = json.loads(Path("packages/contracts/schemas/research-response.v1.schema.json").read_text(encoding="utf-8"))
    transport = FakeBrokerTransport(json.dumps(response))
    execution = RagStrategy(
        strategy_id="R3.hybrid-rrf.v1", broker=_client(transport), retriever=StaticRetriever(),
        snapshot=snapshot.path, response_schema=schema,
    ).execute(
        query="¿Quién dirige Atlas?",
        target_model={"provider": "local", "deployment": "desktop", "model": "test"},
        correlation_id="corr-rag",
    )

    assert source in execution.exact_context
    assert execution.verification is not None
    assert execution.verification.deterministic_pass is True
    assert source in transport.calls[0][3]["content"]["prompt"]


def test_task_client_authenticates_like_the_capability_negotiator() -> None:
    """El Broker autentica /api/v1/* con X-Admin-Token; Bearer devuelve 403."""
    transport = FakeBrokerTransport("plain response")
    B0Strategy(_client(transport)).execute(
        query="Hello", target_model={"provider": "local", "deployment": "desktop", "model": "test"},
        correlation_id="corr-auth",
    )

    for _method, _url, headers, _payload in transport.calls:
        assert headers.get("X-Admin-Token") == "secret"
        assert "Authorization" not in headers


def test_task_timeout_follows_max_wait_so_the_broker_does_not_kill_a_slow_local_model() -> None:
    transport = FakeBrokerTransport("plain response")
    client = BrokerTaskClient(
        endpoint="http://127.0.0.1:8765", token="secret", transport=transport,
        poll_interval=0, max_wait=1200,
    )
    B0Strategy(client).execute(
        query="Hello", target_model={"provider": "local", "deployment": "desktop", "model": "test"},
        correlation_id="corr-timeout",
    )

    submitted = transport.calls[0][3]
    assert submitted["execution"]["timeout_seconds"] == 1200
    assert submitted["generation"]["max_output_tokens"] >= 4000
    assert submitted["generation"]["seed"] is not None


def test_broker_errors_carry_the_response_body_so_a_403_is_distinguishable() -> None:
    class FailingTransport:
        def request(self, method, url, *, headers, body, timeout):
            return BrokerHttpResponse(403, b'{"detail":"ADMIN_AUTH_REQUIRED"}')

    client = BrokerTaskClient(
        endpoint="http://127.0.0.1:8765", token="secret", transport=FailingTransport(),
        poll_interval=0, max_wait=1,
    )
    with pytest.raises(BrokerInvocationError, match="ADMIN_AUTH_REQUIRED"):
        B0Strategy(client).execute(
            query="Hello",
            target_model={"provider": "local", "deployment": "desktop", "model": "test"},
            correlation_id="corr-403",
        )
