from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import sha256_json


class RealBenchmarkValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RealBenchmarkSuite:
    path: Path
    definition: dict[str, Any]
    fingerprint: str

    @classmethod
    def load(cls, path: Path, *, require_approval: bool = True) -> RealBenchmarkSuite:
        source = path.resolve(strict=True)
        definition = json.loads(source.read_text(encoding="utf-8"))
        cls._validate(definition, require_approval=require_approval)
        return cls(source, definition, sha256_json(definition))

    @staticmethod
    def _validate(definition: Any, *, require_approval: bool) -> None:
        if not isinstance(definition, dict) or definition.get("schema_version") != "real-benchmark.v1":
            raise RealBenchmarkValidationError("unsupported real benchmark schema")
        if definition.get("purpose") != "external_validity" or definition.get("training_eligible") is not False:
            raise RealBenchmarkValidationError("real benchmark must be external-validity only and training-ineligible")
        snapshot_hash = definition.get("snapshot_hash", "")
        if len(snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in snapshot_hash):
            raise RealBenchmarkValidationError("real benchmark requires an exact snapshot SHA-256")
        review = definition.get("human_review", {})
        if require_approval and review.get("status") != "approved":
            raise RealBenchmarkValidationError("real benchmark is pending human approval")
        if review.get("reviewer_kind") != "human" or not review.get("reviewer"):
            raise RealBenchmarkValidationError("real benchmark approval must come from an identified human")
        cases = definition.get("cases")
        if not isinstance(cases, list) or not cases:
            raise RealBenchmarkValidationError("real benchmark requires at least one case")
        ids: set[str] = set()
        for case in cases:
            case_id = case.get("case_id") if isinstance(case, dict) else None
            if not case_id or case_id in ids:
                raise RealBenchmarkValidationError("real benchmark case ids must be unique")
            ids.add(case_id)
            if not isinstance(case.get("query"), str) or not case["query"].strip():
                raise RealBenchmarkValidationError(f"case {case_id} requires a query")
            reference = case.get("reference_answer", {})
            if reference.get("author_kind") != "human" or not reference.get("author"):
                raise RealBenchmarkValidationError(f"case {case_id} reference answer must be human-authored")
            if not isinstance(reference.get("answer"), str) or not reference["answer"].strip():
                raise RealBenchmarkValidationError(f"case {case_id} requires a reference answer")
            evidence = reference.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise RealBenchmarkValidationError(f"case {case_id} requires recoverable evidence")
            for item in evidence:
                required = {"note_id", "note_path", "section", "chunk_id", "source_reference"}
                if not isinstance(item, dict) or not required <= item.keys():
                    raise RealBenchmarkValidationError(f"case {case_id} has incomplete evidence")
