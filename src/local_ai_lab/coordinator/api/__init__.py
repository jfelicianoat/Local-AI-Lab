"""API HTTP del Coordinator.

Partida como pedia la auditoria, por quien la llama:

- `modelos`     — los cuerpos de peticion, todos estrictos.
- `auxiliares`  — token de sesion y traduccion de errores a HTTP.
- `rutas_app`   — lo que consume el escritorio (`/app/v1`).
- `rutas_nodo`  — el protocolo Coordinator/Worker (`/node/v1`).

`create_app` sigue siendo el unico punto de entrada.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.coordinator.api.rutas_app import registrar_rutas_app
from local_ai_lab.coordinator.api.rutas_nodo import registrar_rutas_nodo

__all__ = ["create_app", "main"]


def create_app(service: CoordinatorService, *, app_token: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Local AI Lab Coordinator",
        version="0.1.0",
        description="Authenticated Coordinator/Worker protocol v1",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Accept", "Authorization", "Content-Type", "Idempotency-Key", "X-App-Token", "X-Node-ID"],
    )

    registrar_rutas_app(app, service, app_token)
    registrar_rutas_nodo(app, service)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local-ai-lab-coordinator")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8711)
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "::1", "localhost") and os.environ.get(
        "LOCAL_AI_LAB_ALLOW_REMOTE_HTTP"
    ) != "I_ACCEPT_NO_TLS_FOR_DEVELOPMENT":
        parser.error("non-loopback binding requires a TLS terminator; development override denied")
    import uvicorn

    session_token = os.environ.get("LOCAL_AI_LAB_APP_TOKEN")
    if not session_token:
        parser.error("LOCAL_AI_LAB_APP_TOKEN must be provided by the desktop launcher")
    uvicorn.run(
        create_app(CoordinatorService(args.database), app_token=session_token),
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
