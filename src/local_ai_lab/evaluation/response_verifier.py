from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from local_ai_lab.knowledge_index.snapshot import SnapshotVerifier

REQUIRED_FIELDS = {
    "answer", "findings", "contradictions", "uncertainties", "missing_information"
}
NUMBER = re.compile(r"(?<!\w)\d[\d.,]*(?:\s*%|\s*[A-Z]{3})?")
PROPER_NAME = re.compile(r"\b(?:[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ-]+\s+){1,3}[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ-]+\b")


@dataclass(frozen=True, slots=True)
class VerificationReport:
    schema_valid: bool
    every_finding_has_evidence: bool
    citation_existence: bool
    note_existence: bool
    chunk_existence: bool
    source_reference_validity: bool
    unsupported_numbers: tuple[str, ...]
    unsupported_names: tuple[str, ...]
    invented_references: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def deterministic_pass(self) -> bool:
        return (
            self.schema_valid
            and self.every_finding_has_evidence
            and self.citation_existence
            and self.note_existence
            and self.chunk_existence
            and self.source_reference_validity
            and not self.unsupported_numbers
            and not self.unsupported_names
            and not self.invented_references
        )

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "deterministic_pass": self.deterministic_pass}


class ResearchResponseVerifier:
    def __init__(self, snapshot: Path) -> None:
        verified = SnapshotVerifier().verify(snapshot)
        self.snapshot_hash = verified["manifest"]["global_hash"]
        self.snapshot_id = verified["manifest"]["snapshot_id"]
        notes = self._jsonl(snapshot / "notes.jsonl")
        chunks = self._jsonl(snapshot / "chunks.jsonl")
        self.notes = {note["note_id"]: note for note in notes}
        self.chunks = {chunk["chunk_id"]: chunk for chunk in chunks}

    def verify(self, response: dict[str, Any]) -> VerificationReport:
        errors: list[str] = []
        schema_valid = self._shape(response, errors)
        findings = response.get("findings", []) if isinstance(response, dict) else []
        every_finding_has_evidence = all(
            isinstance(item, dict) and bool(item.get("evidence")) for item in findings
        )
        if not every_finding_has_evidence:
            errors.append("every factual finding must have at least one evidence reference")
        evidence_items: list[dict[str, Any]] = []
        claims: list[tuple[str, list[dict[str, Any]]]] = []
        for item in findings if isinstance(findings, list) else []:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence", [])
            if isinstance(evidence, list):
                evidence_items.extend(ref for ref in evidence if isinstance(ref, dict))
                claims.append((str(item.get("claim", "")), [ref for ref in evidence if isinstance(ref, dict)]))
        for contradiction in response.get("contradictions", []) if isinstance(response, dict) else []:
            if isinstance(contradiction, dict) and isinstance(contradiction.get("evidence"), list):
                evidence_items.extend(ref for ref in contradiction["evidence"] if isinstance(ref, dict))

        invented: list[str] = []
        note_valid = True
        chunk_valid = True
        source_valid = True
        for ref in evidence_items:
            note = self.notes.get(ref.get("note_id"))
            chunk = self.chunks.get(ref.get("chunk_id"))
            label = str(ref.get("source_reference", ref.get("chunk_id", "unknown")))
            if note is None:
                note_valid = False
                invented.append(label)
            if chunk is None:
                chunk_valid = False
                invented.append(label)
            if note is not None and ref.get("note_path") != note["relative_path"]:
                source_valid = False
                invented.append(label)
            if chunk is not None and (
                ref.get("note_id") != chunk["note_id"]
                or ref.get("section") != chunk["section"]
            ):
                source_valid = False
                invented.append(label)
            expected = f"snapshot:sha256:{self.snapshot_hash}#chunk:{ref.get('chunk_id', '')}"
            if ref.get("snapshot_id") != self.snapshot_id or ref.get("source_reference") != expected:
                source_valid = False
                invented.append(label)

        unsupported_numbers: list[str] = []
        unsupported_names: list[str] = []
        for claim, refs in claims:
            cited_text = "\n".join(
                self.chunks[ref["chunk_id"]]["content"]
                for ref in refs if ref.get("chunk_id") in self.chunks
            )
            normalized_evidence_numbers = {self._number_key(value) for value in NUMBER.findall(cited_text)}
            unsupported_numbers.extend(
                value for value in NUMBER.findall(claim)
                if self._number_key(value) not in normalized_evidence_numbers
            )
            evidence_folded = cited_text.casefold()
            unsupported_names.extend(
                value for value in PROPER_NAME.findall(claim)
                if value.casefold() not in evidence_folded
            )
        return VerificationReport(
            schema_valid=schema_valid,
            every_finding_has_evidence=every_finding_has_evidence,
            citation_existence=bool(evidence_items) or not findings,
            note_existence=note_valid,
            chunk_existence=chunk_valid,
            source_reference_validity=source_valid,
            unsupported_numbers=tuple(sorted(set(unsupported_numbers))),
            unsupported_names=tuple(sorted(set(unsupported_names))),
            invented_references=tuple(sorted(set(invented))),
            errors=tuple(errors),
        )

    @staticmethod
    def _shape(response: Any, errors: list[str]) -> bool:
        if not isinstance(response, dict) or set(response) != REQUIRED_FIELDS:
            errors.append("response must contain exactly the canonical top-level fields")
            return False
        if not isinstance(response["answer"], str):
            errors.append("answer must be a string")
        for name in ("findings", "contradictions", "uncertainties", "missing_information"):
            if not isinstance(response[name], list):
                errors.append(f"{name} must be a list")
        for finding in response["findings"] if isinstance(response["findings"], list) else []:
            if not isinstance(finding, dict) or set(finding) != {"claim", "evidence"}:
                errors.append("finding must contain exactly claim and evidence")
        return not errors

    @staticmethod
    def _number_key(value: str) -> str:
        return re.sub(r"[.,\s]", "", value).casefold()

    @staticmethod
    def _jsonl(path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
