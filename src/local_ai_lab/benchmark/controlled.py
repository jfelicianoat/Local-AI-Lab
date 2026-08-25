from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import sha256_json

CASE_KINDS = {
    "single_hop", "multi_hop", "contradiction", "numeric", "entity",
    "missing_information", "distractor",
}


class SuiteValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    document_id: str
    relative_path: str
    sha256: str
    content: str


@dataclass(frozen=True, slots=True)
class ControlledCorpusSuite:
    root: Path
    definition: dict[str, Any]
    documents: tuple[CorpusDocument, ...]
    fingerprint: str

    @classmethod
    def load(cls, root: Path, *, require_human_approval: bool = False) -> ControlledCorpusSuite:
        base = root.resolve(strict=True)
        definition = json.loads((base / "suite.json").read_text(encoding="utf-8"))
        if not isinstance(definition, dict):
            raise SuiteValidationError("suite.json must contain an object")
        documents: list[CorpusDocument] = []
        for item in definition.get("documents", []):
            relative_path = item.get("relative_path", "")
            candidate = (base / relative_path).resolve(strict=True)
            try:
                candidate.relative_to(base)
            except ValueError as error:
                raise SuiteValidationError("document path escapes the suite") from error
            raw = candidate.read_bytes()
            documents.append(
                CorpusDocument(
                    document_id=item["document_id"],
                    relative_path=relative_path,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    content=raw.decode("utf-8"),
                )
            )
        cls._validate(definition, documents, require_human_approval=require_human_approval)
        fingerprint = sha256_json(
            {
                "definition": definition,
                "documents": [
                    {"document_id": doc.document_id, "relative_path": doc.relative_path, "sha256": doc.sha256}
                    for doc in documents
                ],
            }
        )
        return cls(base, definition, tuple(documents), fingerprint)

    @property
    def cases(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.definition["cases"])

    @property
    def review_status(self) -> str:
        return self.definition["human_review"]["status"]

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "controlled-corpus-manifest.v1",
            "suite_id": self.definition["suite_id"],
            "suite_version": self.definition["suite_version"],
            "purpose": "benchmark_only",
            "training_eligible": False,
            "fingerprint": self.fingerprint,
            "documents": [
                {"document_id": item.document_id, "relative_path": item.relative_path, "sha256": item.sha256}
                for item in self.documents
            ],
            "case_ids": [case["case_id"] for case in self.cases],
            "human_review": self.definition["human_review"],
        }

    @staticmethod
    def _validate(
        definition: dict[str, Any],
        documents: list[CorpusDocument],
        *,
        require_human_approval: bool,
    ) -> None:
        required = {"schema_version", "suite_id", "suite_version", "purpose", "training_eligible", "documents", "cases", "human_review"}
        missing = required - definition.keys()
        if missing:
            raise SuiteValidationError(f"missing suite fields: {sorted(missing)}")
        if definition["schema_version"] != "controlled-corpus.v1":
            raise SuiteValidationError("unsupported controlled corpus schema")
        if definition["purpose"] != "benchmark_only" or definition["training_eligible"] is not False:
            raise SuiteValidationError("controlled corpus must be benchmark-only and training-ineligible")
        review = definition["human_review"]
        if review.get("status") not in {"pending", "approved", "rejected"}:
            raise SuiteValidationError("invalid human review status")
        if require_human_approval and review.get("status") != "approved":
            raise SuiteValidationError("ground truth is pending human approval")
        document_ids = [document.document_id for document in documents]
        if len(document_ids) != len(set(document_ids)):
            raise SuiteValidationError("document ids must be unique")
        declared_ids = [item.get("document_id") for item in definition["documents"]]
        if document_ids != declared_ids:
            raise SuiteValidationError("loaded documents do not match their declarations")
        known = set(document_ids)
        case_ids: set[str] = set()
        observed_kinds: set[str] = set()
        for case in definition["cases"]:
            case_id = case.get("case_id")
            if not case_id or case_id in case_ids:
                raise SuiteValidationError("case ids must be present and unique")
            case_ids.add(case_id)
            kinds = set(case.get("kinds", []))
            if not kinds or not kinds <= CASE_KINDS:
                raise SuiteValidationError(f"invalid case kinds: {case_id}")
            observed_kinds.update(kinds)
            truth = case.get("ground_truth", {})
            relevant = set(truth.get("relevant_document_ids", []))
            irrelevant = set(truth.get("irrelevant_document_ids", []))
            if relevant & irrelevant or relevant | irrelevant != known:
                raise SuiteValidationError(f"case {case_id} must classify every document exactly once")
            for relation in truth.get("relations", []):
                if relation.get("source") not in known or relation.get("target") not in known:
                    raise SuiteValidationError(f"case {case_id} references an unknown relation document")
            for fact in truth.get("facts", []):
                if fact.get("document_id") not in relevant:
                    raise SuiteValidationError(f"case {case_id} fact is not backed by a relevant document")
            for contradiction in truth.get("contradictions", []):
                pair = {contradiction.get("left_document_id"), contradiction.get("right_document_id")}
                if not pair <= relevant:
                    raise SuiteValidationError(f"case {case_id} contradiction is not fully relevant")
        if observed_kinds != CASE_KINDS:
            raise SuiteValidationError(f"suite does not cover all required kinds: {sorted(CASE_KINDS - observed_kinds)}")
