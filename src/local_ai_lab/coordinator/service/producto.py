"""Espacio de producto: vision general, evidencias de fase y revisiones.

Es la capa que mira el humano: que hay hecho, que esta pendiente de
revisar y que correcciones se han aplicado.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.knowledge_index.projection import KnowledgeIndex
from local_ai_lab.knowledge_index.snapshot import SnapshotVerifier
from local_ai_lab.retrieval.engine import LexicalRetriever
from local_ai_lab.coordinator.service.misiones import MisionesMixin


class ProductoMixin(MisionesMixin):
    """Espacio de producto: vision general, evidencias de fase y revisiones."""

    def _manual_example_hits(self, *, snapshot_id: str, index_id: str, query: str) -> list[dict[str, str]]:
        snapshot_record = self.repository.product_record(snapshot_id)
        index_record = self.repository.product_record(index_id)
        if (snapshot_record is None or snapshot_record["category"] != "snapshot"
                or snapshot_record["status"] != "COMPLETE"
                or index_record is None or index_record["category"] != "index"
                or index_record["status"] != "READY"
                or index_record["summary"].get("snapshot_id") != snapshot_id
                or index_record["summary"].get("snapshot_hash") != snapshot_record["artifact_sha256"]):
            raise ValueError("manual example requires a complete snapshot and its matching index")
        snapshot = self.repository.artifact_location(snapshot_id, expected_kind="vault_snapshot")
        verified = SnapshotVerifier().verify(snapshot)
        if verified["manifest"]["global_hash"] != snapshot_record["artifact_sha256"]:
            raise ValueError("manual example snapshot has changed")
        index_path = self.repository.artifact_location(index_id, expected_kind="knowledge_index")
        if hashlib.sha256(index_path.read_bytes()).hexdigest() != index_record["artifact_sha256"]:
            raise ValueError("manual example index has changed")
        with sqlite3.connect(f"file:{index_path.as_posix()}?mode=ro", uri=True) as db:
            row = db.execute("SELECT value FROM build_metadata WHERE key='snapshot_global_hash'").fetchone()
        if row is None or row[0] != snapshot_record["artifact_sha256"]:
            raise ValueError("manual example index points to another snapshot")
        hits = LexicalRetriever(KnowledgeIndex(index_path)).retrieve(query, limit=20)
        return [
            {"chunk_id": item.chunk_id, "note_id": item.note_id,
             "note_path": item.relative_path, "section": item.section,
             "content": item.content, "source_reference": item.evidence_reference}
            for item in hits
        ]

    def preview_manual_example(self, *, snapshot_id: str, index_id: str, query: str) -> list[dict[str, str]]:
        if not query.strip():
            raise ValueError("manual example query must be non-empty")
        return self._manual_example_hits(snapshot_id=snapshot_id, index_id=index_id, query=query)

    def create_manual_example_review(
        self, *, snapshot_id: str, index_id: str, query: str, answer: str,
        chunk_ids: list[str], reviewer: str,
    ) -> dict[str, Any]:
        if not query.strip() or not answer.strip() or not reviewer.strip() or not chunk_ids:
            raise ValueError("manual example needs a question, answer, reviewer and cited chunks")
        hits = self._manual_example_hits(snapshot_id=snapshot_id, index_id=index_id, query=query)
        snapshot_hash = self.repository.product_record(snapshot_id)["artifact_sha256"]
        query_key = " ".join(query.casefold().split())
        for benchmark in self.product_workspace()["benchmarks"]:
            if benchmark["status"] != "HUMAN_APPROVED" or benchmark["summary"].get("snapshot_hash") != snapshot_hash:
                continue
            definition = json.loads(self.repository.artifact_location(
                benchmark["record_id"], expected_kind="real_benchmark_suite"
            ).read_text(encoding="utf-8"))
            if any(" ".join(case["query"].casefold().split()) == query_key for case in definition["cases"]):
                raise ValueError("manual training example duplicates an approved benchmark question")
        by_id = {hit["chunk_id"]: hit for hit in hits}
        if len(set(chunk_ids)) != len(chunk_ids) or any(chunk_id not in by_id for chunk_id in chunk_ids):
            raise ValueError("manual example citations must come from the shown retrieval results")
        chosen = [by_id[chunk_id] for chunk_id in chunk_ids]
        response = {
            "answer": answer.strip(),
            "findings": [{"claim": answer.strip(), "evidence": [
                {key: hit[key] for key in (
                    "note_id", "note_path", "section", "chunk_id", "source_reference"
                )} | {"snapshot_id": snapshot_id}
                for hit in chosen
            ]}],
            "contradictions": [], "uncertainties": [], "missing_information": [],
        }
        run_id = f"manual:{uuid.uuid4()}"
        return self.feedback.create_review(
            run_id=run_id, case_id=run_id, snapshot_id=snapshot_id, reviewer=reviewer.strip(),
            run_context={
                "query": query.strip(), "strategy_id": "manual_authorized_example.v1",
                "model": "human", "prompt": "Respuesta y citas aportadas por una persona",
                "retrieval_config": {"strategy": "R1", "index_id": index_id, "k": 20},
                "snapshot_id": snapshot_id, "retrieved_context": chosen,
                "estimated_tokens": None,
                "cost": {"amount": None, "currency": "USD", "source": "not_available", "verification_status": "unknown"},
            },
            original_response=response,
        )

    def create_pairing_code(self, valid_seconds: int = 300) -> str:
        return self.repository.create_pairing_code(valid_seconds)

    def overview(self) -> dict[str, Any]:
        self._recover_expired_jobs()
        return self.repository.overview()

    def record_phase_evidence(self, **evidence: Any) -> dict[str, Any]:
        return self.repository.record_phase_evidence(**evidence)

    def product_workspace(self) -> dict[str, Any]:
        return self.repository.product_workspace()

    def product_workspace_page(self, *, limit: int = 50,
                               groups: list[str] | None = None,
                               cursors: dict[str, dict[str, str] | None] | None = None) -> dict[str, Any]:
        return self.repository.product_workspace_page(limit=limit, groups=groups, cursors=cursors)

    def jobs(self) -> list[dict[str, Any]]:
        self._recover_expired_jobs()
        return self.repository.jobs_view()

    def jobs_page(self, *, limit: int = 50,
                  cursor: dict[str, str] | None = None) -> dict[str, Any]:
        self._recover_expired_jobs()
        return self.repository.jobs_page(limit=limit, cursor=cursor)

    def record_product_item(self, **item: Any) -> dict[str, Any]:
        return self.repository.record_product_item(**item)

    def reviews(self) -> list[dict[str, Any]]:
        return self.feedback.list_reviews()

    def reviews_page(self, *, limit: int = 50,
                     cursor: dict[str, str] | None = None) -> dict[str, Any]:
        return self.feedback.list_reviews_page(limit=limit, cursor=cursor)

    def product_artifact(self, record_id: str) -> tuple[Path, str, str]:
        record = self.repository.product_record(record_id)
        if record is None or record["category"] not in {"experiment", "export"}:
            raise KeyError("no downloadable report or export for this record")
        if record["category"] == "experiment" and record["status"] in {"LOCAL_VERIFIED", "PENDING_HUMAN_REVIEW"}:
            path = self.repository.artifact_location(record_id, expected_kind="retrieval_benchmark_report")
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["artifact_sha256"]:
                raise ValueError("local experiment report has changed")
            return path, "application/json", f"informe-{record_id}.json"
        historical_result = record["status"] == "RESULT_REQUIRES_VALIDATION"
        if record["status"] not in {"EXPERIMENT_SUCCEEDED", "EXPORT_SUCCEEDED"} and not historical_result:
            raise ValueError("the selected result is not complete")
        digest = record["artifact_sha256"]
        if not self.artifacts.verify(digest):
            raise ValueError("result package is missing or corrupt")
        prefix = "exportacion" if record["category"] == "export" else "informe"
        return self.artifacts.blob_path(digest), "application/zip", f"{prefix}-{record_id}.zip"

    def save_review_correction(
        self, *, review_id: str, actor: str, corrected_response: dict[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        review = self.feedback.get(review_id)
        snapshot = self.repository.artifact_location(
            review["snapshot_id"], expected_kind="vault_snapshot"
        )
        return self.feedback.save_correction(
            review_id, actor=actor, corrected_response=corrected_response,
            verifier=ResearchResponseVerifier(snapshot),
            expected_revision=expected_revision,
        )

    def transition_review(self, *, review_id: str, to_state: str, actor: str,
                          reason: str | None = None, expected_revision: int | None = None) -> dict[str, Any]:
        return self.feedback.transition_review(review_id, to_state=to_state, actor=actor,
                                               reason=reason, expected_revision=expected_revision)

    def transition_training_candidate(
        self, *, review_id: str, to_state: str, actor: str, expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return self.feedback.transition_training(review_id, to_state=to_state, actor=actor,
                                                 expected_revision=expected_revision)
