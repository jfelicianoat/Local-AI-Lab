from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_lab.dataset.factory import DatasetError, DatasetFactory, DatasetVerifier
from local_ai_lab.feedback.repository import FeedbackRepository


class PassingReport:
    deterministic_pass = True

    def as_dict(self):
        return {"deterministic_pass": True}


class PassingVerifier:
    def verify(self, response):
        return PassingReport()


def _approved(repository: FeedbackRepository, *, run: str, case: str, reviewer: str):
    response = {
        "answer": "Respuesta corregida.", "findings": [], "contradictions": [],
        "uncertainties": [], "missing_information": ["No consta."],
    }
    context = {
        "query": "Consulta real", "strategy_id": "R3.hybrid-rrf.v1",
        "model": "local/model", "prompt": "Responde con evidencia.",
        "retrieval_config": {"k": 5}, "snapshot_id": "snapshot-real",
        "retrieved_context": [],
        "estimated_tokens": None,
        "cost": {"amount": None, "currency": "USD", "source": "not_available", "verification_status": "unknown"},
    }
    review = repository.create_review(
        run_id=run, case_id=case, snapshot_id="snapshot-real", reviewer=reviewer,
        run_context=context, original_response=response,
    )
    repository.save_correction(
        review["review_id"], actor=reviewer, corrected_response=response,
        verifier=PassingVerifier(),
    )
    repository.transition_review(review["review_id"], to_state="submitted", actor=reviewer)
    repository.transition_review(review["review_id"], to_state="accepted", actor="lead")
    repository.transition_training(review["review_id"], to_state="proposed", actor=reviewer)
    return repository.transition_training(review["review_id"], to_state="approved", actor="lead")


def test_dataset_excludes_benchmarks_deduplicates_and_keeps_provenance(tmp_path: Path) -> None:
    repository = FeedbackRepository(tmp_path / "feedback.sqlite3")
    real = _approved(repository, run="run-real", case="real-case", reviewer="ana")
    benchmark = _approved(repository, run="run-bench", case="atlas-owner", reviewer="bea")
    duplicate = _approved(repository, run="run-duplicate", case="other-real-case", reviewer="carla")

    result = DatasetFactory().build(
        repository, tmp_path / "datasets", name="approved-feedback-v1",
        benchmark_case_ids={"atlas-owner"}, benchmark_fingerprints={"a" * 64},
        split_seed="fixed-seed",
    )
    manifest = DatasetVerifier().verify(result.path)

    assert manifest["counts"]["included"] == 1
    assert manifest["counts"]["excluded"] == 2
    assert real["review_id"] in result.exported_review_ids
    assert benchmark["review_id"] in result.excluded_review_ids
    assert duplicate["review_id"] in result.excluded_review_ids
    records = []
    for split in ("train", "validation", "test"):
        records.extend(
            line for line in (result.path / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        )
    assert "run-real" in records[0]
    assert "atlas-owner" not in records[0]


def test_dataset_verifier_rejects_tampering(tmp_path: Path) -> None:
    repository = FeedbackRepository(tmp_path / "feedback.sqlite3")
    _approved(repository, run="run-real", case="real-case", reviewer="ana")
    result = DatasetFactory().build(
        repository, tmp_path / "datasets", name="dataset",
        benchmark_case_ids=set(), benchmark_fingerprints=set(), split_seed="seed",
    )
    audit = result.path / "audit.jsonl"
    audit.write_text(audit.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="artifact hash mismatch"):
        DatasetVerifier().verify(result.path)


def test_dataset_cannot_be_built_only_from_benchmark_cases(tmp_path: Path) -> None:
    repository = FeedbackRepository(tmp_path / "feedback.sqlite3")
    _approved(repository, run="run-bench", case="atlas-owner", reviewer="ana")

    with pytest.raises(DatasetError, match="no eligible approved examples"):
        DatasetFactory().build(
            repository, tmp_path / "datasets", name="dataset",
            benchmark_case_ids={"atlas-owner"}, benchmark_fingerprints={"a" * 64},
            split_seed="seed",
        )
