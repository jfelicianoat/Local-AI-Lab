"""Autenticacion de la sesion de escritorio y traduccion de errores a HTTP.

`_call` es el unico sitio donde un error del dominio se convierte en un
codigo HTTP: sin el, cada ruta elegiria el suyo y el cliente no podria
distinguir un conflicto de un dato invalido.
"""
from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import Header, HTTPException

from local_ai_lab.coordinator.repository import CoordinatorConflict, LeaseRejected
from local_ai_lab.coordinator.service import (
    AuthenticationError,
    IdempotencyConflict,
)
from local_ai_lab.knowledge_index.snapshot import SnapshotError
from local_ai_lab.knowledge_index.vault import VaultSecurityError


def _require_app_token(expected: str | None, supplied: str | None) -> None:
    if expected is None or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(401, "valid desktop session token required")


def _node_credentials(
    x_node_id: Annotated[str, Header(alias="X-Node-ID")],
    authorization: Annotated[str, Header(alias="Authorization")],
) -> tuple[str, str]:
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Bearer node credential required")
    return x_node_id, token


def _call(operation: Any, **kwargs: Any) -> Any:
    try:
        return operation(**kwargs)
    except AuthenticationError as error:
        raise HTTPException(401, str(error)) from error
    except IdempotencyConflict as error:
        raise HTTPException(409, str(error)) from error
    except LeaseRejected as error:
        raise HTTPException(409, str(error)) from error
    except CoordinatorConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, SnapshotError, VaultSecurityError) as error:
        raise HTTPException(422, str(error)) from error
