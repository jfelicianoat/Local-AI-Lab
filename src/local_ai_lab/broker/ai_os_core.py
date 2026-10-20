"""AI OS Core como director: pide permiso antes de cada invocación al Broker.

Core es el plano de control del ecosistema del TFM. El laboratorio no lo necesita: sin
``LOCAL_AI_LAB_CORE_URL`` todo sigue igual. Con él, ``BrokerTaskClient.invoke`` evalúa
antes la política ``local_ai_lab:broker`` y solo envía con un ALLOW ejecutable; si Core
no contesta **no se envía** (quien configuró un director no quiere que se le salte
cuando se cae). Cada tarea deja recibos en Core con su clave de idempotencia.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any


POLICY_SCOPE = "local_ai_lab:broker"
#: Cómo se presenta el laboratorio ante Core (debe coincidir con su token por app).
PRINCIPAL = "local_ai_lab"
ENV_URL = "LOCAL_AI_LAB_CORE_URL"
ENV_TOKEN = "LOCAL_AI_LAB_CORE_TOKEN"
#: Un salto para el monitor de Core nunca debe hacer esperar al experimento.
HOP_TIMEOUT_SECONDS = 3
_TERMINAL = {"succeeded", "failed_terminal", "cancelled"}


def flow_id_for(operation_id: str) -> str:
    """El flujo del monitor de Core: la clave de idempotencia, en un formato que Core acepta."""
    return re.sub(r"[^A-Za-z0-9_.:\-]", "_", operation_id)[:128] or "lab"


class CoreGateError(RuntimeError):
    """Core no autoriza o no contesta: la invocación no se envía."""


class LabCoreGate:
    def __init__(self, base_url: str, token: str | None = None, *, transport: Any = None):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"{ENV_URL} debe ser una URL http o https")
        self.base_url = base_url.rstrip("/")
        self.token = token
        if transport is None:
            from local_ai_lab.broker.client import UrllibBrokerTaskTransport  # el cliente importa este módulo

            transport = UrllibBrokerTaskTransport()
        self.transport = transport
        #: Cuándo salió cada invocación hacia el Broker (latencia en el monitor de Core).
        self._sent_at: dict[str, tuple[float, str]] = {}

    def authorize(self, operation_id: str, body: dict[str, Any]) -> int | None:
        """Lanza sin ALLOW ejecutable; si no, el turno en la cola del Broker que el director
        fijó al laboratorio en el monitor (None = sin fijar)."""
        risk = body.get("risk") if isinstance(body.get("risk"), dict) else {}
        decision = self._post("/api/v1/policies/evaluate", {
            "scope": POLICY_SCOPE, "principal_id": PRINCIPAL, "resource_id": operation_id,
            "context": {
                "operation_type": "experiment_invocation",
                "data_classification": str(risk.get("data_classification") or "confidential"),
                "model": "/".join(body["model_requirements"]["target_model"].values()),
                "flow_id": flow_id_for(operation_id),
            },
        })
        if decision.get("authorization") != "ALLOW" or decision.get("executable") is not True:
            authorization = decision.get("authorization")
            missing = ", ".join(decision.get("unknown_inputs") or [])
            raise CoreGateError(
                f"AI OS Core no autoriza la invocación ({authorization}{': falta ' + missing if missing else ''}); "
                f"revisa las políticas de «{POLICY_SCOPE}». No se ha enviado nada al Broker."
            )
        priority = decision.get("broker_priority")
        return priority if isinstance(priority, int) else None

    def receipt(self, operation_id: str, status: str, task_id: str) -> None:
        """Un recibo perdido no tumba el experimento: Core verá el siguiente estado."""
        flow = flow_id_for(operation_id)
        try:
            self._post("/api/v1/operations/receipts", {
                "operation_id": operation_id, "receiver_service": "ai_broker",
                "status": status, "evidence": {"task_id": task_id, "flow_id": flow},
            })
        except CoreGateError:
            pass
        # Monitor de Core: enviar es la petición al Broker; el estado terminal, su respuesta
        if status == "accepted":
            self._sent_at[operation_id] = (time.monotonic(), task_id)
            self.hop(flow, "request", "invocación del experimento", {"task_id": task_id})
        elif status in _TERMINAL:
            details: dict[str, Any] = {"task_id": task_id, "status": status}
            began = self._sent_at.pop(operation_id, None)
            if began is not None:
                details["latency_ms"] = int((time.monotonic() - began[0]) * 1000)
            self.hop(flow, "response" if status == "succeeded" else "error", status, details)

    def hop(self, flow_id: str, kind: str, summary: str = "", details: dict[str, Any] | None = None) -> None:
        """Cuenta al monitor de Core lo que se manda al Broker. Enviar y olvidar."""
        try:
            self._post("/api/v1/flows/hops", {
                "flow_id": flow_id, "source_system": PRINCIPAL, "target_system": "ai_broker",
                "kind": kind, "summary": summary[:200], "details": details or {},
            }, timeout=HOP_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 — el monitor es secundario: jamás para un experimento
            pass

    def _post(self, path: str, payload: dict[str, Any], timeout: float = 10) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json", "X-Principal-Id": PRINCIPAL}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.transport.request(
                "POST", self.base_url + path, headers=headers,
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=timeout,
            )
        except (OSError, TimeoutError) as error:
            raise CoreGateError(
                "No se pudo consultar a AI OS Core; por seguridad no se ha enviado nada al Broker."
            ) from error
        if response.status >= 400:
            detail = response.body.decode("utf-8", "replace")[:300]
            raise CoreGateError(f"AI OS Core respondió {response.status}: {detail}")
        value = json.loads(response.body.decode("utf-8") or "{}")
        return value if isinstance(value, dict) else {}


def core_connection(principal: str = "local_ai_lab") -> tuple[str, str] | None:
    """URL y token de esta app en Core, tal como Core los deja en su carpeta de conexión.

    Core genera un token por app y lo escribe en %LOCALAPPDATA%/AIOSCore/conexion: así no
    hay que pegar ninguno. En una máquina sin Core (un Worker del PC IA), None.
    """
    local = os.environ.get("LOCALAPPDATA")
    folder = os.environ.get("AI_OS_CONNECT_DIR") or (str(Path(local, "AIOSCore", "conexion")) if local else "")
    if not folder:
        return None
    try:
        data = json.loads(Path(folder, f"{principal}.json").read_text(encoding="utf-8"))
        url, token = str(data["core_url"]), str(data["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (url, token) if url and token else None


def core_settings() -> tuple[str, str | None] | None:
    """LOCAL_AI_LAB_CORE_URL/_TOKEN y, si faltan, los que deja Core al arrancar."""
    url = os.environ.get(ENV_URL, "").strip()
    token = os.environ.get(ENV_TOKEN, "").strip() or None
    found = core_connection()
    if found and (not url or url.rstrip("/") == found[0].rstrip("/")):
        url, token = url or found[0], token or found[1]
    return (url, token) if url else None


def core_from_environment() -> LabCoreGate | None:
    core = core_settings()
    return LabCoreGate(core[0], core[1]) if core else None


class CoreBrokerToken:
    """El token del AI Broker, pedido a Core: el Broker lo rota en cada arranque.

    Se llama en cada petición; `refresh=True` (tras un 401/403 del Broker) lo vuelve a pedir.
    """

    def __init__(self, core_url: str, core_token: str, timeout: float = 5.0) -> None:
        self._url = core_url.rstrip("/") + "/api/v1/credentials/broker"
        self._core_token = core_token
        self._timeout = timeout
        self._token: str | None = None

    def __call__(self, refresh: bool = False) -> str | None:
        if refresh or self._token is None:
            self._token = self._fetch() or self._token
        return self._token

    def _fetch(self) -> str | None:
        request = urllib.request.Request(self._url, headers={
            "Authorization": f"Bearer {self._core_token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - URL de Core
                token = json.load(response).get("token")
        except (OSError, ValueError, AttributeError):
            return None
        return token if isinstance(token, str) and token else None


def broker_token_source() -> CoreBrokerToken | None:
    """Con Core, el token del Broker lo da Core: nadie lo pega."""
    core = core_settings()
    return CoreBrokerToken(core[0], core[1]) if core and core[1] else None
