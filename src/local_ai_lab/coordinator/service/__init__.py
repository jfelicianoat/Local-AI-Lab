"""Orquestacion central de casos de uso del Coordinator.

El servicio esta partido por contexto acotado, que era la recomendacion de
la auditoria, y en el orden en que dependen unos de otros:

- `base`          — estado, autenticacion e idempotencia.
- `producto`      — vision general, evidencias y revisiones.
- `conocimiento`  — vaults e indices.
- `evaluacion`    — benchmarks, deriva y compatibilidad (mide).
- `estrategias`   — seleccion y experimentos (decide con lo medido).
- `entrenamiento` — datasets, preflight, entrenamiento y exportacion.
- `nodos`         — emparejamiento y artefactos.
- `trabajos`      — ciclo de vida de un trabajo.

`CoordinatorService` los recompone. La API sigue importando esta clase.
"""
from __future__ import annotations

from local_ai_lab.coordinator.service.base import AuthenticationError, IdempotencyConflict
from local_ai_lab.coordinator.service.trabajos import TrabajosMixin

__all__ = ["AuthenticationError", "CoordinatorService", "IdempotencyConflict"]


class CoordinatorService(TrabajosMixin):
    """Todos los casos de uso del Coordinator, en una sola fachada."""
