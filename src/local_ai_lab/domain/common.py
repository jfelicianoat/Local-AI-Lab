from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def publish_directory(staging: Path, final: Path, *, attempts: int = 6) -> Path:
    """Publica un directorio de staging renombrándolo, reintentando el bloqueo de Windows.

    En Windows un antivirus o el indexador pueden mantener abierto un fichero recién
    escrito y hacer fallar el rename con WinError 5 aunque nada esté mal. Es transitorio,
    y sobre almacenamiento sincronizado (Google Drive, red) ocurre bastante más que en
    disco local. Un rename sin reintento convierte eso en un snapshot perdido.
    """
    delay = 0.1
    for attempt in range(attempts):
        try:
            staging.rename(final)
            return final
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    return final


def new_id() -> str:
    return str(uuid.uuid7())


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
