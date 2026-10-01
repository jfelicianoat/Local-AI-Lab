"""A frozen execution view for either the bundled or a human-approved suite."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.benchmark.real import RealBenchmarkSuite
from local_ai_lab.knowledge_index.snapshot import SnapshotVerifier


@dataclass(frozen=True, slots=True)
class RealExecutionSuite:
    definition: dict[str, Any]
    fingerprint: str

    @property
    def cases(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.definition["cases"])

    @property
    def review_status(self) -> str:
        return "approved"


def load_execution_suite(suite_root: Path, snapshot: Path) -> ControlledCorpusSuite | RealExecutionSuite:
    real_file = suite_root / "real-benchmark.json"
    if not real_file.is_file():
        return ControlledCorpusSuite.load(suite_root, require_human_approval=False)
    suite = RealBenchmarkSuite.load(real_file, require_approval=True)
    RealBenchmarkSuite.validate_against_snapshot(suite.definition, snapshot)
    manifest = SnapshotVerifier().verify(snapshot)["manifest"]
    notes = [
        json.loads(line) for line in (snapshot / "notes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    document_ids = {note["note_id"] for note in notes}
    cases = []
    for case in suite.definition["cases"]:
        relevant = {ref["note_id"] for ref in case["reference_answer"]["evidence"]}
        cases.append({
            **case,
            "kinds": case.get("kinds", ["single_hop"]),
            "ground_truth": {
                "relevant_document_ids": sorted(relevant),
                "irrelevant_document_ids": sorted(document_ids - relevant),
            },
        })
    return RealExecutionSuite(
        definition={
            "suite_id": suite.definition.get("suite_id", real_file.stem),
            "documents": [
                {"document_id": note["note_id"], "relative_path": note["relative_path"]}
                for note in notes
            ],
            "cases": cases,
            "snapshot_hash": manifest["global_hash"],
        },
        fingerprint=suite.fingerprint,
    )
