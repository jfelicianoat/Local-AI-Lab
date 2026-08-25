from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from local_ai_lab.benchmark.controlled import CASE_KINDS, ControlledCorpusSuite, SuiteValidationError

SUITE = Path("benchmarks/controlled/v1")


def test_controlled_suite_covers_required_cases_and_is_never_training_data() -> None:
    suite = ControlledCorpusSuite.load(SUITE)
    observed = {kind for case in suite.cases for kind in case["kinds"]}

    assert observed == CASE_KINDS
    assert suite.review_status == "pending"
    assert suite.manifest()["training_eligible"] is False
    assert len(suite.fingerprint) == 64
    assert len(suite.documents) == 6


def test_ground_truth_classifies_every_document_for_every_case() -> None:
    suite = ControlledCorpusSuite.load(SUITE)
    all_documents = {document.document_id for document in suite.documents}

    for case in suite.cases:
        truth = case["ground_truth"]
        relevant = set(truth["relevant_document_ids"])
        irrelevant = set(truth["irrelevant_document_ids"])
        assert relevant.isdisjoint(irrelevant)
        assert relevant | irrelevant == all_documents


def test_human_gate_cannot_pass_while_review_is_pending() -> None:
    with pytest.raises(SuiteValidationError, match="pending human approval"):
        ControlledCorpusSuite.load(SUITE, require_human_approval=True)


def test_fingerprint_detects_document_drift(tmp_path: Path) -> None:
    copy = tmp_path / "suite"
    shutil.copytree(SUITE, copy)
    original = ControlledCorpusSuite.load(copy).fingerprint
    document = copy / "documents" / "atlas-overview.md"
    document.write_text(document.read_text(encoding="utf-8") + "\nCambio.", encoding="utf-8")

    assert ControlledCorpusSuite.load(copy).fingerprint != original


def test_validator_rejects_training_contamination_flag(tmp_path: Path) -> None:
    copy = tmp_path / "suite"
    shutil.copytree(SUITE, copy)
    definition_path = copy / "suite.json"
    definition = json.loads(definition_path.read_text(encoding="utf-8"))
    definition["training_eligible"] = True
    definition_path.write_text(json.dumps(definition), encoding="utf-8")

    with pytest.raises(SuiteValidationError, match="training-ineligible"):
        ControlledCorpusSuite.load(copy)
