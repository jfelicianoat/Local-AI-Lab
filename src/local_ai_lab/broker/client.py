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


#: Roles que el Broker ejecuta por su cuenta, para brokers anteriores al 2.10
#: que no marcan `contractual`. El vocabulario real tiene quince roles y crece,
#: así que nombrarlos es frágil por definición: contra un 2.10 esto no se usa.
LEGACY_NON_CONTRACTUAL_ROLES = frozenset({"shadow_probe"})


def is_contractual(item: Mapping[str, Any]) -> bool:
    """Si esta invocación ejecuta el trabajo que se pidió (Client_API.md, 8.1).

    Bajo un mismo `task_id` conviven las llamadas de la tarea y las que el
    Broker lanza para medir su catálogo. El contrato 2.10 lo declara con un
    booleano justamente para que nadie mantenga una lista negra de roles.
    """
    declared = item.get("contractual")
    if isinstance(declared, bool):
        return declared
    return item.get("role") not in LEGACY_NON_CONTRACTUAL_ROLES


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
    #: Contrato 2.10 (8.1): solo las invocaciones que ejecutan esta tarea. Es lo
    #: que hay que mirar para validar la política de ejecución; el resto es
    #: trabajo del Broker que ni se factura ni respeta el `target_model`.
    contractual_telemetry: tuple[dict[str, Any], ...] = ()
    #: Contrato 2.10 (8.4): roles de las invocaciones que NO son de esta tarea.
    #: Vacío es la respuesta deseable: nadie más vio el contenido.
    auxiliary_roles: tuple[str, ...] = ()
    #: Contrato 2.10 (8.5): la poda que se aplicó de verdad al prompt. `None`
    #: significa que el Broker no lo declara, no que no hubiera poda.
    prompt_compression: str | None = None
    #: Contrato 2.10 (8.3): sha256 del artefacto marcado `final: true`, que
    #: cierra sobre los bytes exactos que produjo el modelo.
    deliverable_sha256: str | None = None


def effective_compression(contractual: tuple[dict[str, Any], ...]) -> str | None:
    """La poda que se aplicó DE VERDAD al prompt (Client_API.md, 8.5).

    La aserción es sobre las invocaciones **contractuales**: el Broker fuerza
    `off` en las que procesan contenido generado —fragmentos de map-reduce,
    síntesis, el juez de confianza—, así que mezclarlas confundiría una política
    con un automatismo. `None` cuando no consta, que no es «no hubo poda»: es un
    Broker anterior al 2.10, o llamadas que no envían prompt de usuario.
    """
    observed: list[str] = []
    for item in contractual:
        echo = item.get("prompt_compression")
        if not isinstance(echo, dict):
            continue
        value = echo.get("effective")
        if isinstance(value, str) and value:
            observed.append(value)
    if not observed:
        return None
    # Si alguna se comprimió, eso es lo que hay que enseñar: decir `off` porque
    # la mayoría lo estaba sería exactamente el dato que el eco viene a destapar.
    for value in observed:
        if value != "off":
            return value
    return "off"


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
        capabilities: Mapping[str, Any] | None = None,
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
        # Lo que promete el Broker EN MARCHA. Se lee una vez, al primer envío, y
        # no en cada petición: solo cambia cuando cambia su configuración. Un
        # campo del 2.10 enviado a un Broker que no lo tiene NO se ignora — la
        # validación es `extra="forbid"` y la petición entera falla con 422—,
        # así que aquí no se supone nada por el número de versión.
        self._capabilities: dict[str, Any] | None = capabilities if capabilities is None else dict(capabilities)
        self._capabilities_read = capabilities is not None

    def capabilities(self) -> dict[str, Any]:
        """`/api/v1/capabilities`, leído una sola vez (Client_API.md, 2).

        Si no se puede leer no se bloquea el trabajo: el propio contrato lo pide
        —un fallo de red, de token o de parseo no significa que el Broker no
        sepa hacer lo que se le pide—. Se devuelve vacío, que hace que los
        campos opcionales del 2.10 no se envíen, y la tarea sale igual.
        """
        if self._capabilities_read:
            return self._capabilities or {}
        self._capabilities_read = True
        try:
            self._capabilities = self._json("GET", "/api/v1/capabilities", None, timeout=10)
        except BrokerInvocationError:
            self._capabilities = None
        return self._capabilities or {}

    def _supports(self, capability: str) -> bool:
        return self.capabilities().get(capability) is True

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
        # Un benchmark sobre un prompt podado no compara lo que dice comparar:
        # el modelo no vio el caso, vio un resumen del caso. Desde el contrato
        # 2.10 esto además tiene acuse de recibo por invocación (8.5).
        if self._supports("prompt_compression_override"):
            body["prompt_compression"] = "off"
        # 8.4: `local_only` ya mantiene el sondeo en sombra dentro de la
        # máquina, pero «local» no es «el modelo bajo prueba». Un experimento
        # que fija el modelo exacto no quiere que su contenido lo vea otro.
        if self._supports("auxiliary_invocations_optout"):
            body["auxiliary_invocations"] = False
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
        items = tuple(item for item in telemetry if isinstance(item, dict))
        contractual = tuple(item for item in items if is_contractual(item))
        auxiliary = tuple(
            str(item.get("role", "unknown")) for item in items if not is_contractual(item)
        )
        return BrokerInvocation(
            task_id, text, model_used if isinstance(model_used, dict) else {}, fallback,
            usage, items, cost_amount,
            "USD", "broker_invocation_telemetry" if raw_cost is not None else "not_available",
            "verified" if raw_cost is not None else "unknown",
            (time.monotonic() - started) * 1000.0,
            contractual_telemetry=contractual,
            auxiliary_roles=tuple(sorted(set(auxiliary))),
            prompt_compression=effective_compression(contractual),
            deliverable_sha256=self._deliverable_sha256(task_id),
        )

    def _deliverable_sha256(self, task_id: str) -> str | None:
        """sha256 del artefacto marcado `final: true` (Client_API.md, 8.3).

        `/artifacts` es la vía canónica para recoger el entregable: viene tipado
        y con su hash sobre los bytes exactos que produjo el modelo. `result` no
        tiene esquema en el OpenAPI y no va a tenerlo, así que un experimento
        que tiene que rendir cuentas después no puede cerrarse solo sobre él.

        Se filtra por el booleano y no por `artifact_type`: la lista de tipos
        crece con cada estrategia nueva, y cerrar con «el primero de la lista»
        cerraría con la imagen que acompaña en vez de con la respuesta.
        """
        if not (self._supports("task_artifacts") and self._supports("canonical_artifacts")):
            return None
        try:
            payload = self._json("GET", f"/api/v1/tasks/{task_id}/artifacts", None, timeout=30)
        except BrokerInvocationError:
            return None
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and item.get("final") is True:
                digest = item.get("sha256")
                if isinstance(digest, str) and digest:
                    return digest
        return None

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
