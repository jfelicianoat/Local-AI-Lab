from __future__ import annotations

import hashlib
import os
import sys
import uuid
import time
from dataclasses import dataclass
from pathlib import Path

from local_ai_lab.benchmark.controlled import ControlledCorpusSuite
from local_ai_lab.benchmark.retrieval_runner import RetrievalBenchmarkRunner
from local_ai_lab.domain.common import canonical_json
from local_ai_lab.knowledge_index.projection import KnowledgeIndex, KnowledgeIndexBuilder
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter
from local_ai_lab.retrieval.engine import LexicalRetriever


@dataclass(frozen=True, slots=True)
class ControlledBenchmarkArtifact:
    experiment_id: str
    suite: ControlledCorpusSuite
    snapshot_id: str
    snapshot_hash: str
    report_path: Path
    report_sha256: str
    report: dict[str, object]


def bundled_controlled_suite_root() -> Path:
    override = os.environ.get("LOCAL_AI_LAB_CONTROLLED_SUITE")
    if override:
        return Path(override).resolve(strict=True)
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    candidate = bundle_root / "benchmarks" / "controlled" / "v1"
    return candidate.resolve(strict=True)


def run_controlled_lexical_benchmark(
    output_root: Path, *, k: int = 5,
) -> ControlledBenchmarkArtifact:
    suite_root = bundled_controlled_suite_root()
    suite = ControlledCorpusSuite.load(suite_root, require_human_approval=False)
    experiment_id = str(uuid.uuid4())
    experiment_root = output_root.resolve() / experiment_id
    experiment_root.mkdir(parents=True, exist_ok=False)

    snapshot = SnapshotBuilder().build(
        ReadOnlyVaultAdapter(allowed_root=suite_root.parent, vault_root=suite_root),
        experiment_root / "snapshots",
    )
    if snapshot.state != "COMPLETE":
        raise RuntimeError("controlled benchmark snapshot did not converge")
    index_path = KnowledgeIndexBuilder().build(
        snapshot.path, experiment_root / "knowledge.sqlite3"
    )
    started = time.perf_counter()
    report = RetrievalBenchmarkRunner().run(
        suite, LexicalRetriever(KnowledgeIndex(index_path)), k=k
    ).payload
    report["latency_ms"] = (time.perf_counter() - started) * 1000.0
    report_path = experiment_root / "retrieval-report.json"
    report_path.write_text(canonical_json(report) + "\n", encoding="utf-8", newline="\n")
    report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
    return ControlledBenchmarkArtifact(
        experiment_id=experiment_id,
        suite=suite,
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.global_hash,
        report_path=report_path,
        report_sha256=report_sha256,
        report=report,
    )
