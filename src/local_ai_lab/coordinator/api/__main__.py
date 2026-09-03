"""Punto de entrada de `python -m local_ai_lab.coordinator.api`.

Existe porque la API dejo de ser un modulo suelto y paso a ser paquete: sin
esto, arrancar el Coordinator con `-m` dejaria de funcionar sin avisar.
"""
from __future__ import annotations

from local_ai_lab.coordinator.api import main

if __name__ == "__main__":
    raise SystemExit(main())
