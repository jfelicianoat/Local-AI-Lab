from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from local_ai_lab.broker.compatibility import normalize_broker_endpoint


class BrokerInvocationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BrokerHttpResponse:
    status: int
    body: bytes


class BrokerTaskTransport(Protocol):
    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> BrokerHttpResponse: ...


class UrllibBrokerTaskTransport:
    def request(self, method, url, *, headers, body, timeout):
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return BrokerHttpResponse(response.status, response.read())
        except urllib.error.HTTPError as error:
            return BrokerHttpResponse(error.code, error.read())


@dataclass(frozen=True, slots=True)
class BrokerInvocation:
    task_id: str
    text: str
    model_used: dict[str, Any]
    fallback_used: bool
    usage: dict[str, Any]
    telemetry: tuple[dict[str, Any], ...]
    cost_amount: str | None
    cost_currency: str
    cost_source: str
    cost_verification_status: str
    latency_ms: float


class BrokerTaskClient:
    def __init__(
        self,
        *,
        endpoint: str,
        token: str | None,
        transport: BrokerTaskTransport | None = None,
        poll_interval: float = 0.5,
        max_wait: float = 300.0,
        task_timeout_seconds: int | None = None,
        generation_defaults: Mapping[str, Any] | None = None,
    ) -> None:
        self.endpoint = normalize_broker_endpoint(endpoint)
        self.token = token
        self.transport = transport or UrllibBrokerTaskTransport()
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        # El timeout que aplica el Broker debe acompañar a max_wait. Si no, esperar más
        # tiempo en el cliente no sirve de nada: la tarea muere antes en el servidor,
        # que es justo lo que ocurre con un modelo local grande cargando desde disco.
        self.task_timeout_seconds = (
            int(task_timeout_seconds) if task_timeout_seconds is not None else max(180, int(max_wait))
        )
        # Una respuesta estructurada con citas no cabe en el presupuesto de salida por
        # defecto del Broker cuando el modelo razona antes de responder, y un benchmark
        # sin semilla no es reproducible. Ambos son configurables por experimento.
        self.generation_defaults: dict[str, Any] = {"max_output_tokens": 8000, "seed": 42}
        if generation_defaults is not None:
            self.generation_defaults.update(generation_defaults)

    def invoke(
        self,
        *,
        prompt: str,
        target_model: dict[str, str],
        generation: dict[str, Any],
        json_schema: dict[str, Any] | None,
        correlation_id: str,
        timeout_seconds: int | None = None,
        execution: dict[str, Any] | None = None,
        client_tool_handler: Callable[[dict[str, Any]], str] | None = None,
    ) -> BrokerInvocation:
        required_model = {"provider", "deployment", "model"}
        if set(target_model) != required_model or any(not value.strip() for value in target_model.values()):
            raise ValueError("target_model must contain exact provider, deployment and model")
        body: dict[str, Any] = {
            "idempotency_key": f"lal:{correlation_id}",
            "request_id": correlation_id,
            "inference_kind": "chat",
            "content": {"prompt": prompt, "metadata": {"origin": "local-ai-lab", "correlation_id": correlation_id}},
            "generation": {**self.generation_defaults, **generation},
            "model_requirements": {"target_model": target_model, "fallback_allowed": False},
            "execution": execution or {
                "strategy": "single", "preset": "fast",
                "timeout_seconds": timeout_seconds if timeout_seconds is not None else self.task_timeout_seconds,
            },
            "risk": {"data_classification": "local_only"},
            "group": "local-ai-lab",
            "exclude_from_model_learning": True,
        }
        if json_schema is not None:
            body["output"] = {"format": "json", "json_schema": json_schema}
        started = time.monotonic()
        submitted = self._json("POST", "/api/v1/tasks", body, timeout=30)
        task_id = submitted.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise BrokerInvocationError("Broker did not return a task_id")
        deadline = time.monotonic() + self.max_wait
        while True:
            state = self._json("GET", f"/api/v1/tasks/{task_id}", None, timeout=30)
            status = state.get("status")
            if status == "waiting_for_tools":
                if client_tool_handler is None:
                    raise BrokerInvocationError("Broker requested client tools but no handler was provided")
                result_payload = state.get("result") if isinstance(state.get("result"), dict) else {}
                pending = result_payload.get("pending_tool_calls", [])
                if not isinstance(pending, list) or not pending:
                    raise BrokerInvocationError("Broker waiting_for_tools state has no pending calls")
                tool_results = []
                for call in pending:
                    if not isinstance(call, dict):
                        raise BrokerInvocationError("Broker returned an invalid client tool call")
                    tool_call_id = call.get("tool_call_id", call.get("id"))
                    if not isinstance(tool_call_id, str):
                        raise BrokerInvocationError("Broker client tool call lacks an id")
                    tool_results.append({
                        "tool_call_id": tool_call_id,
                        "content": client_tool_handler(call),
                    })
                self._json(
                    "POST", f"/api/v1/tasks/{task_id}/tool_results",
                    {"tool_results": tool_results}, timeout=30,
                )
                continue
            if status in {"completed", "succeeded", "failed", "cancelled"}:
                break
            if time.monotonic() >= deadline:
                raise BrokerInvocationError(f"Broker task {task_id} timed out")
            time.sleep(self.poll_interval)
        if status not in {"completed", "succeeded"}:
            raise BrokerInvocationError(f"Broker task {task_id} ended as {status}: {state.get('error')}")
        result_payload = state.get("result") if isinstance(state.get("result"), dict) else state
        summary = state.get("execution_summary") if isinstance(state.get("execution_summary"), dict) else {}
        fallback = summary.get("fallback_used") is True or result_payload.get("fallback_used") is True
        if fallback:
            raise BrokerInvocationError("Broker used fallback despite fallback_allowed=false")
        model_used = summary.get("served_by") or result_payload.get("model_used") or {}
        if isinstance(model_used, dict) and all(key in model_used for key in required_model):
            if any(model_used[key] != target_model[key] for key in required_model):
                raise BrokerInvocationError("Broker served a model other than the exact target")
        text = result_payload.get("assistant_content", result_payload.get("result_markdown"))
        if not isinstance(text, str):
            raise BrokerInvocationError("Broker succeeded without assistant_content")
        telemetry_payload = self._json(
            "GET", f"/api/v1/tasks/{task_id}/invocations", None, timeout=30
        )
        telemetry = telemetry_payload.get("items", [])
        if not isinstance(telemetry, list):
            raise BrokerInvocationError("Broker invocation telemetry contract is invalid")
        usage = result_payload.get("usage") if isinstance(result_payload.get("usage"), dict) else {}
        raw_cost = usage.get("cost_actual_usd", usage.get("cost_usd"))
        cost_amount = str(raw_cost) if raw_cost is not None else None
        return BrokerInvocation(
            task_id, text, model_used if isinstance(model_used, dict) else {}, fallback,
            usage, tuple(item for item in telemetry if isinstance(item, dict)), cost_amount,
            "USD", "broker_invocation_telemetry" if raw_cost is not None else "not_available",
            "verified" if raw_cost is not None else "unknown",
            (time.monotonic() - started) * 1000.0,
        )

    def _json(self, method: str, path: str, payload: dict[str, Any] | None, *, timeout: float) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.token:
            # El Broker autentica /api/v1/* con X-Admin-Token, no con Authorization: Bearer.
            # Es la misma cabecera que ya usa el negociador de capacidades.
            headers["X-Admin-Token"] = self.token
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self.transport.request(
            method, self.endpoint + path, headers=headers, body=body, timeout=timeout
        )
        if response.status < 200 or response.status >= 300:
            # Sin el cuerpo, un 403 ADMIN_AUTH_REQUIRED y un 422 de contrato son
            # indistinguibles para quien depura la integración.
            detail = response.body.decode("utf-8", "replace").strip()[:500]
            suffix = f": {detail}" if detail else ""
            raise BrokerInvocationError(
                f"Broker {method} {path} returned HTTP {response.status}{suffix}"
            )
        try:
            value = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BrokerInvocationError("Broker returned invalid JSON") from error
        if not isinstance(value, dict):
            raise BrokerInvocationError("Broker response must be an object")
        return value
