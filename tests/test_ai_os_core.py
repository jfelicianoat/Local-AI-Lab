"""AI OS Core dirige las invocaciones del laboratorio: sin su ALLOW no sale nada.

Core se simula con el mismo protocolo de transporte que el Broker (formas de Core
0.2.1); el recorrido contra los servicios reales está en scripts/verify_ai_os_core.py.
"""
from __future__ import annotations

import json

import pytest

from local_ai_lab.broker.ai_os_core import LabCoreGate, core_from_environment
from local_ai_lab.broker.client import BrokerHttpResponse, BrokerInvocationError, BrokerTaskClient
from test_generation_strategies import FakeBrokerTransport

TARGET = {"provider": "local", "deployment": "desktop", "model": "test"}  # lo que sirve el doble


class FakeCore:
    def __init__(self, authorization: str = "ALLOW", *, down: bool = False, monitor_down: bool = False) -> None:
        self.authorization = authorization
        self.down = down
        self.monitor_down = monitor_down
        self.calls: list[tuple[str, dict]] = []

    def request(self, method, url, *, headers, body, timeout):
        if self.down or (self.monitor_down and url.endswith("/flows/hops")):
            raise ConnectionRefusedError("Core apagado")
        assert headers["X-Principal-Id"] == "local_ai_lab"
        assert headers["Authorization"] == "Bearer tok-lab"
        payload = json.loads(body)
        self.calls.append((url, payload))
        if url.endswith("/policies/evaluate"):
            reply = {"authorization": self.authorization, "executable": self.authorization == "ALLOW"}
            return BrokerHttpResponse(200, json.dumps(reply).encode())
        return BrokerHttpResponse(201, b"{}")


def _client(broker: FakeBrokerTransport, core: FakeCore) -> BrokerTaskClient:
    return BrokerTaskClient(
        endpoint="http://127.0.0.1:8765", token="secret", transport=broker, poll_interval=0, max_wait=1,
        core=LabCoreGate("http://core.test", "tok-lab", transport=core),
    )


def _broker_tasks(broker: FakeBrokerTransport) -> list:
    return [call for call in broker.calls if call[0] == "POST" and call[1].endswith("/api/v1/tasks")]


def _invoke(client: BrokerTaskClient):
    return client.invoke(prompt="Hola", target_model=TARGET, generation={}, json_schema=None, correlation_id="c-1")


@pytest.mark.parametrize("decision", ["DENY", "REQUIRE_APPROVAL", "INDETERMINATE"])
def test_without_allow_nothing_reaches_the_broker(decision: str) -> None:
    broker, core = FakeBrokerTransport("respuesta"), FakeCore(decision)
    with pytest.raises(BrokerInvocationError, match="AI OS Core no autoriza"):
        _invoke(_client(broker, core))
    assert _broker_tasks(broker) == []
    (evaluation,) = [payload for _, payload in core.calls]
    assert evaluation["scope"] == "local_ai_lab:broker"
    assert evaluation["context"] == {
        "operation_type": "experiment_invocation",
        "data_classification": "local_only",
        "model": "local/desktop/test",
        "flow_id": "lal:c-1",
    }


def test_core_down_fails_closed() -> None:
    broker = FakeBrokerTransport("respuesta")
    with pytest.raises(BrokerInvocationError, match="No se pudo consultar a AI OS Core"):
        _invoke(_client(broker, FakeCore(down=True)))
    assert _broker_tasks(broker) == []


def test_allow_invokes_and_leaves_receipts() -> None:
    broker, core = FakeBrokerTransport("respuesta"), FakeCore()
    result = _invoke(_client(broker, core))
    assert len(_broker_tasks(broker)) == 1
    receipts = [payload for url, payload in core.calls if url.endswith("/receipts")]
    assert [r["status"] for r in receipts] == ["accepted", "succeeded"]
    assert {r["operation_id"] for r in receipts} == {"lal:c-1"}
    assert result.text == "respuesta"


def test_the_invocation_is_seen_in_the_core_monitor() -> None:
    """Local AI Lab 0.1.2: recibos y saltos comparten flujo (la clave de idempotencia)."""
    broker, core = FakeBrokerTransport("respuesta"), FakeCore()
    _invoke(_client(broker, core))
    receipts = [payload for url, payload in core.calls if url.endswith("/receipts")]
    assert {r["evidence"]["flow_id"] for r in receipts} == {"lal:c-1"}
    hops = [payload for url, payload in core.calls if url.endswith("/flows/hops")]
    assert [h["kind"] for h in hops] == ["request", "response"]
    assert {(h["flow_id"], h["source_system"], h["target_system"]) for h in hops} == {
        ("lal:c-1", "local_ai_lab", "ai_broker")}
    assert hops[1]["details"]["latency_ms"] >= 0


def test_a_monitor_that_is_down_never_stops_the_experiment() -> None:
    broker = FakeBrokerTransport("respuesta")
    assert _invoke(_client(broker, FakeCore(monitor_down=True))).text == "respuesta"


def test_core_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_AI_LAB_CORE_URL", raising=False)
    assert core_from_environment() is None
    assert BrokerTaskClient(endpoint="http://127.0.0.1:8765", token=None).core is None
    monkeypatch.setenv("LOCAL_AI_LAB_CORE_URL", "http://127.0.0.1:8000")
    assert BrokerTaskClient(endpoint="http://127.0.0.1:8765", token=None).core is not None


def test_sin_pegar_tokens_core_da_el_del_broker_y_se_renueva(tmp_path, monkeypatch) -> None:
    """Core deja su conexión al laboratorio y le da el token del Broker, que se renueva tras un 403."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    vigente = ["broker-1"]

    class Core(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            ok = self.headers.get("Authorization") == "Bearer tok-lab"
            self.send_response(200 if ok else 401)
            self.end_headers()
            self.wfile.write(json.dumps({"token": vigente[0]} if ok else {}).encode())

        def log_message(self, *_) -> None:
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Core)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{servidor.server_port}"
        monkeypatch.setenv("AI_OS_CONNECT_DIR", str(tmp_path))
        monkeypatch.delenv("LOCAL_AI_LAB_CORE_URL", raising=False)
        monkeypatch.delenv("LOCAL_AI_LAB_CORE_TOKEN", raising=False)
        (tmp_path / "local_ai_lab.json").write_text(json.dumps({"core_url": url, "token": "tok-lab"}))
        assert core_from_environment() is not None

        vistos = []

        class Broker:
            def request(self, method, url, *, headers, body, timeout):
                vistos.append(headers.get("X-Admin-Token"))
                ok = headers.get("X-Admin-Token") == vigente[0]
                return BrokerHttpResponse(200 if ok else 403, b"{}" if ok else b'{"detail":"ADMIN_AUTH_REQUIRED"}')

        client = BrokerTaskClient(endpoint="http://127.0.0.1:8765", token="pegado-caducado",
                                  transport=Broker(), core=None)
        client._json("GET", "/api/v1/capabilities", None, timeout=5)
        vigente[0] = "broker-2"  # el Broker se reinicia; el runner publica el nuevo en Core
        client._json("GET", "/api/v1/capabilities", None, timeout=5)
        assert vistos == ["broker-1", "broker-1", "broker-2"]
    finally:
        servidor.shutdown()
