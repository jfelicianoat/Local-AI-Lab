"""Persistencia del Coordinator y transiciones de trabajos.

Partido por agregado, que era la recomendacion de la auditoria:

- `conversion`   — funciones puras sobre especificaciones y requisitos.
- `base`         — esquema, conflictos y guardas de lease.
- `nodos`        — emparejamiento, registro y latidos.
- `trabajos`     — cola y maquina de estados.
- `capacidades`  — evidencia de capacidades y vision general.
- `producto`     — registros de producto y artefactos.
"""
from __future__ import annotations

from local_ai_lab.coordinator.repository.base import CoordinatorConflict, LeaseRejected
from local_ai_lab.coordinator.repository.producto import ProductoMixin

__all__ = ["CoordinatorConflict", "CoordinatorRepository", "LeaseRejected"]


class CoordinatorRepository(ProductoMixin):
    """Persistencia completa del Coordinator."""
