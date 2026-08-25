from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.feedback.repository import FeedbackRepository, FeedbackStateError
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter


def _fixture(tmp_path: Path):
    allowed = tmp_path / "Vaults"
    vault = allowed / "Test"
    vault.mkdir(parents=True)
    (vault / "Atlas.md").write_text("# Owner\nAna Torres dirige Atlas.", encoding="utf-8")
    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=allowed, vault_root=vault),
        tmp_path / "snapshots", vault_id=str(uuid.uuid4()),
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
    response = {
        "answer": "Ana Torres dirige Atlas.",
        "findings": [{"claim": "Ana Torres dirige Atlas.", "evidence": [evidence]}],
        "contradictions": [], "uncertainties": [], "missing_information": [],
    }
    context = {
        "query": "¿Quién dirige Atlas?", "strategy_id": "R3.hybrid-rrf.v1",
        "model": "local/test-model", "prompt": "Responde con evidencia.",
        "retrieval_config": {"k": 5}, "snapshot_id": snapshot.snapshot_id,
        "retrieved_context": [evidence],
        "estimated_tokens": 24,
        "cost": {"amount": None, "currency": "USD", "source": "not_available", "verification_status": "unknown"},
    }
    return snapshot, ResearchResponseVerifier(snapshot.path), response, context


def test_feedback_keeps_diff_verification_and_append_only_events(tmp_path: Path) -> None:
    snapshot, verifier, corrected, context = _fixture(tmp_path)
    repository = FeedbackRepository(tmp_path / "feedback.sqlite3")
    review = repository.create_review(
        run_id="run-1", case_id="case-1", snapshot_id=snapshot.snapshot_id,
        reviewer="reviewer@example", run_context=context,
        original_response={**corrected, "answer": "Respuesta original."},
    )
    review = repository.save_correction(
        review["review_id"], actor="reviewer@example", corrected_response=corrected,
        verifier=verifier,
    )
    review = repository.transition_review(
        review["review_id"], to_state="submitted", actor="reviewer@example"
    )
    review = repository.transition_review(
        review["review_id"], to_state="accepted", actor="lead@example"
    )

    assert review["status"] == "accepted"
    assert review["context"]["cost"]["amount"] is None
    assert review["verification"]["deterministic_pass"] is True
    assert "-  \"answer\": \"Respuesta original.\"" in review["diff_text"]
    assert [event["event_type"] for event in review["events"]] == [
        "review_created", "correction_saved", "review_transition", "review_transition"
    ]


def test_training_candidate_requires_acceptance_and_two_explicit_transitions(tmp_path: Path) -> None:
    snapshot, verifier, corrected, context = _fixture(tmp_path)
    repository = FeedbackRepository(tmp_path / "feedback.sqlite3")
    review = repository.create_review(
        run_id="run-1", case_id="case-1", snapshot_id=snapshot.snapshot_id,
        reviewer="ana", run_context=context, original_response=corrected,
    )
    with pytest.raises(FeedbackStateError, match="only accepted"):
        repository.transition_training(review["review_id"], to_state="proposed", actor="ana")
    repository.save_correction(review["review_id"], actor="ana", corrected_response=corrected, verifier=verifier)
    repository.transition_review(review["review_id"], to_state="submitted", actor="ana")
    repository.transition_review(review["review_id"], to_state="accepted", actor="lead")
    proposed = repository.transition_training(review["review_id"], to_state="proposed", actor="ana")

    assert proposed["training_state"] == "proposed"
    assert proposed["training_state"] != "approved"
    approved = repository.transition_training(review["review_id"], to_state="approved", actor="lead")
    assert approved["training_state"] == "approved"


def test_invalid_correction_cannot_be_submitted(tmp_path: Path) -> None:
    snapshot, verifier, corrected, context = _fixture(tmp_path)
    repository = FeedbackRepository(tmp_path / "feedback.sqlite3")
    review = repository.create_review(
        run_id="run-1", case_id="case-1", snapshot_id=snapshot.snapshot_id,
        reviewer="ana", run_context=context, original_response=corrected,
    )
    corrected["findings"][0]["evidence"] = []
    repository.save_correction(review["review_id"], actor="ana", corrected_response=corrected, verifier=verifier)

    with pytest.raises(FeedbackStateError, match="does not pass"):
        repository.transition_review(review["review_id"], to_state="submitted", actor="ana")


def test_feedback_repository_migrates_legacy_review_table(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE reviews(
               review_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, case_id TEXT NOT NULL,
               snapshot_id TEXT NOT NULL, reviewer TEXT NOT NULL, status TEXT NOT NULL,
               training_state TEXT NOT NULL, original_json TEXT NOT NULL,
               original_sha256 TEXT NOT NULL, corrected_json TEXT, corrected_sha256 TEXT,
               verification_json TEXT, diff_text TEXT, created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL, UNIQUE(run_id, case_id, reviewer))"""
        )

    FeedbackRepository(database)

    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(reviews)")}
    assert "context_json" in columns
