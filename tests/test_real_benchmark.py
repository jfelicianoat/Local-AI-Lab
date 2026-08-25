from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai_lab.benchmark.real import RealBenchmarkSuite, RealBenchmarkValidationError


def _definition() -> dict:
    return {
        "schema_version": "real-benchmark.v1", "suite_id": "real-research-v1",
        "version": "1.0.0", "purpose": "external_validity", "training_eligible": False,
        "snapshot_hash": "a" * 64,
        "human_review": {
            "status": "approved", "reviewer_kind": "human", "reviewer": "Ana",
            "reviewed_at": "2026-08-23T00:00:00Z",
        },
        "cases": [{
            "case_id": "project-evolution", "query": "¿Cómo evolucionó el proyecto?",
            "reference_answer": {
                "author_kind": "human", "author": "Ana", "answer": "Respuesta humana.",
                "evidence": [{
                    "note_id": "note-1", "note_path": "Project.md", "section": "Decision",
                    "chunk_id": "b" * 64,
                    "source_reference": "snapshot:sha256:" + "a" * 64 + "#chunk:" + "b" * 64,
                }],
            },
        }],
    }


def test_real_benchmark_requires_human_reference_and_is_not_training_data(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(_definition()), encoding="utf-8")
    suite = RealBenchmarkSuite.load(path)

    assert suite.definition["training_eligible"] is False
    assert suite.definition["human_review"]["reviewer_kind"] == "human"
    assert len(suite.fingerprint) == 64


def test_real_benchmark_rejects_model_authored_ground_truth(tmp_path: Path) -> None:
    definition = _definition()
    definition["cases"][0]["reference_answer"]["author_kind"] = "model"
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(definition), encoding="utf-8")

    with pytest.raises(RealBenchmarkValidationError, match="human-authored"):
        RealBenchmarkSuite.load(path)


def test_real_benchmark_pending_review_cannot_close_gate(tmp_path: Path) -> None:
    definition = _definition()
    definition["human_review"]["status"] = "pending"
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(definition), encoding="utf-8")

    with pytest.raises(RealBenchmarkValidationError, match="pending human approval"):
        RealBenchmarkSuite.load(path)
