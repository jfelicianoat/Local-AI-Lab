from __future__ import annotations

import json
import uuid
from pathlib import Path

from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter


def _verifier_and_evidence(tmp_path: Path):
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Atlas.md").write_text(
        "# Budget\nEl Proyecto Atlas está dirigido por Ana Torres y tiene 120.000 EUR.",
        encoding="utf-8",
    )
    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=allowed, vault_root=vault),
        tmp_path / "snapshots",
        vault_id=str(uuid.uuid4()),
    )
    note = json.loads((snapshot.path / "notes.jsonl").read_text(encoding="utf-8"))
    chunk = json.loads((snapshot.path / "chunks.jsonl").read_text(encoding="utf-8"))
    evidence = {
        "snapshot_id": snapshot.snapshot_id,
        "note_id": note["note_id"],
        "note_path": note["relative_path"],
        "section": chunk["section"],
        "chunk_id": chunk["chunk_id"],
        "source_reference": f"snapshot:sha256:{snapshot.global_hash}#chunk:{chunk['chunk_id']}",
    }
    return ResearchResponseVerifier(snapshot.path), evidence


def test_response_with_exact_evidence_and_supported_facts_passes(tmp_path: Path) -> None:
    verifier, evidence = _verifier_and_evidence(tmp_path)
    response = {
        "answer": "Atlas tiene un presupuesto documentado.",
        "findings": [{"claim": "Ana Torres dirige el proyecto con 120000 EUR.", "evidence": [evidence]}],
        "contradictions": [],
        "uncertainties": [],
        "missing_information": [],
    }

    report = verifier.verify(response)
    assert report.deterministic_pass is True
    assert report.unsupported_numbers == ()
    assert report.invented_references == ()


def test_invented_chunk_and_unsupported_number_are_rejected(tmp_path: Path) -> None:
    verifier, evidence = _verifier_and_evidence(tmp_path)
    evidence["chunk_id"] = "0" * 64
    response = {
        "answer": "No verificado.",
        "findings": [{"claim": "Ana Torres dispone de 999000 EUR.", "evidence": [evidence]}],
        "contradictions": [],
        "uncertainties": [],
        "missing_information": [],
    }

    report = verifier.verify(response)
    assert report.deterministic_pass is False
    assert report.chunk_existence is False
    assert "999000 EUR" in report.unsupported_numbers
    assert report.invented_references


def test_missing_information_response_does_not_require_invented_citation(tmp_path: Path) -> None:
    verifier, _ = _verifier_and_evidence(tmp_path)
    response = {
        "answer": "No hay evidencia suficiente.",
        "findings": [],
        "contradictions": [],
        "uncertainties": [],
        "missing_information": ["No consta la disponibilidad objetivo."],
    }

    assert verifier.verify(response).deterministic_pass is True


def test_finding_without_evidence_fails_even_when_shape_is_valid(tmp_path: Path) -> None:
    verifier, _ = _verifier_and_evidence(tmp_path)
    response = {
        "answer": "Afirmación sin prueba.",
        "findings": [{"claim": "Atlas tiene un presupuesto.", "evidence": []}],
        "contradictions": [],
        "uncertainties": [],
        "missing_information": [],
    }

    report = verifier.verify(response)
    assert report.schema_valid is True
    assert report.every_finding_has_evidence is False
    assert report.deterministic_pass is False
