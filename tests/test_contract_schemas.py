from __future__ import annotations

import json
from pathlib import Path

from local_ai_lab.coordinator.service import CoordinatorService


SCHEMAS = Path("packages/contracts/schemas")


def test_all_contract_schemas_are_parseable_and_versioned() -> None:
    schemas = list(SCHEMAS.glob("*.schema.json"))
    assert schemas
    for path in schemas:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["$id"].endswith(path.name)


def test_overview_matches_canonical_required_shape(tmp_path: Path) -> None:
    schema = json.loads((SCHEMAS / "overview.v1.schema.json").read_text(encoding="utf-8"))
    overview = CoordinatorService(tmp_path / "state.db").overview()

    assert set(overview) == set(schema["required"])
    assert overview["schema_version"] == schema["properties"]["schema_version"]["const"]
    required_evidence = set(
        json.loads((SCHEMAS / "phase-evidence.v1.schema.json").read_text(encoding="utf-8"))["required"]
    )
    assert all(set(item) == required_evidence for item in overview["evidence"])


def test_workspace_matches_canonical_required_shape(tmp_path: Path) -> None:
    schema = json.loads((SCHEMAS / "workspace.v1.schema.json").read_text(encoding="utf-8"))
    workspace = CoordinatorService(tmp_path / "state.db").product_workspace()

    assert set(workspace) == set(schema["required"])
    assert workspace["schema_version"] == schema["properties"]["schema_version"]["const"]


def test_runtime_response_schema_matches_the_canonical_contract() -> None:
    """El schema que se envía al Broker debe exigir lo mismo que verifica el nivel 1.

    Si divergen, el modelo no puede saber qué forma de cita se le va a exigir y la
    verificación determinista falla siempre por una razón que no es de calidad.
    """
    from local_ai_lab.agents.executor import RESPONSE_SCHEMA

    canonical = json.loads(
        Path("packages/contracts/schemas/research-response.v1.schema.json").read_text(encoding="utf-8")
    )

    assert RESPONSE_SCHEMA["required"] == canonical["required"]

    runtime_finding = RESPONSE_SCHEMA["properties"]["findings"]["items"]
    canonical_finding = canonical["properties"]["findings"]["items"]
    assert runtime_finding["required"] == canonical_finding["required"]

    runtime_evidence = runtime_finding["properties"]["evidence"]["items"]
    canonical_evidence = canonical["$defs"]["evidence"]
    assert sorted(runtime_evidence["required"]) == sorted(canonical_evidence["required"])
    assert sorted(runtime_evidence["properties"]) == sorted(canonical_evidence["properties"])
