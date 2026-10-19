"""Recorrido real: AI OS Core decide si el laboratorio invoca al AI Broker de verdad.

Uso: python scripts/verify_ai_os_core.py <core_url> <token_lab> <token_director> <broker_url> [modelo]
     con LOCAL_AI_LAB_BROKER_TOKEN en el entorno. Modelo por defecto ollama/local/gemma4:12b.

Usa el `BrokerTaskClient` real (el que usan estrategias, agentes y destilación), sin
experimentos ni datos del laboratorio. Core ha de tener las políticas de
`sembrar_ecosistema.py` y el token por app de local_ai_lab; el token director (común)
pone y quita la política DENY.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_lab.broker.ai_os_core import LabCoreGate  # noqa: E402
from local_ai_lab.broker.client import BrokerInvocationError, BrokerTaskClient  # noqa: E402

CORE, TOK_LAB, TOK_DIR, BROKER = sys.argv[1:5]
provider, deployment, model = (sys.argv[5] if len(sys.argv) > 5 else "ollama/local/gemma4:12b").split("/")
TARGET = {"provider": provider, "deployment": deployment, "model": model}
director = httpx.Client(base_url=CORE, headers={"Authorization": f"Bearer {TOK_DIR}"}, timeout=10)
ok = 0


def step(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}", flush=True)
    if not cond:
        sys.exit(1)
    ok += 1


def client(core_url: str) -> BrokerTaskClient:
    return BrokerTaskClient(endpoint=BROKER, token=os.environ["LOCAL_AI_LAB_BROKER_TOKEN"], max_wait=600,
                            generation_defaults={"max_output_tokens": 1024}, core=LabCoreGate(core_url, TOK_LAB))


def invoke(lab: BrokerTaskClient, correlation: str):
    return lab.invoke(prompt="Responde solo con la palabra LABORATORIO.", target_model=TARGET,
                      generation={"temperature": 0}, json_schema=None, correlation_id=correlation)


def raises(lab: BrokerTaskClient, correlation: str) -> str:
    try:
        invoke(lab, correlation)
    except BrokerInvocationError as error:
        return str(error)
    return ""


run = uuid.uuid4().hex[:8]
deny = {"policy_id": "verify_lab_deny", "policy_key": "verify_lab_deny", "scope": "local_ai_lab:broker",
        "decision_if_matched": "DENY",
        "conditions": [{"field": "operation_type", "operator": "equals", "value": "experiment_invocation"}]}
step("director pone DENY", director.post("/api/v1/policies", json=deny).status_code in (200, 201))
error = raises(client(CORE), f"verify-deny-{run}")
step("con DENY no se invoca", "AI OS Core no autoriza" in error, error[:140])
status = director.post("/api/v1/operations/status", json={"operation_id": f"lal:verify-deny-{run}",
                                                           "target_service_id": "ai_broker"}).json()
step("con DENY Core no tiene recibo de envío", status.get("status") in (None, "not_seen"), str(status)[:120])
step("director quita DENY", director.post("/api/v1/policies", json={**deny, "enabled": False}).status_code in (200, 201))

error = raises(client("http://127.0.0.1:9"), f"verify-down-{run}")
step("con Core caído no se invoca", "No se pudo consultar a AI OS Core" in error, error[:140])

result = invoke(client(CORE), f"verify-allow-{run}")
step("con ALLOW responde el modelo exacto del Broker real", {k: result.model_used[k] for k in TARGET} == TARGET,
     f"{result.model_used} -> {result.text[:60]!r}")
status = director.post("/api/v1/operations/status", json={"operation_id": f"lal:verify-allow-{run}",
                                                           "target_service_id": "ai_broker"}).json()
step("Core tiene el recibo succeeded", status.get("status") == "succeeded", str(status)[:200])
print(f"\n{ok} comprobaciones OK")
