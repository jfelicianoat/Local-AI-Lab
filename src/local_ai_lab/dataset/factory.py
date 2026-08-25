from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from local_ai_lab.domain.common import canonical_json, publish_directory, sha256_json, utc_timestamp
from local_ai_lab.feedback.repository import FeedbackRepository

DATASET_FORMAT = "local-ai-lab.dataset.v1"
SPLITS = ("train", "validation", "test")


class DatasetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetResult:
    path: Path
    dataset_id: str
    fingerprint: str
    exported_review_ids: tuple[str, ...]
    excluded_review_ids: tuple[str, ...]


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return "".join(canonical_json(item) + "\n" for item in records).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DatasetFactory:
    """Builds immutable datasets only from explicitly approved feedback."""

    def build(
        self,
        repository: FeedbackRepository,
        output_root: Path,
        *,
        name: str,
        benchmark_case_ids: Iterable[str],
        benchmark_fingerprints: Iterable[str],
        split_seed: str,
    ) -> DatasetResult:
        if not name.strip() or not split_seed:
            raise ValueError("dataset name and split seed must be non-empty")
        root = output_root.resolve()
        if str(root).startswith(("\\\\", "//")):
            raise DatasetError("datasets must be built on local storage")
        blocked_cases = set(benchmark_case_ids)
        benchmark_hashes = sorted(set(benchmark_fingerprints))
        examples: list[dict[str, Any]] = []
        audit: list[dict[str, Any]] = []
        seen: set[str] = set()
        exported: list[str] = []
        excluded: list[str] = []
        for candidate in repository.list_training_candidates(state="approved"):
            review_id = candidate["review_id"]
            if candidate["case_id"] in blocked_cases:
                excluded.append(review_id)
                audit.append({"review_id": review_id, "decision": "excluded", "reason": "benchmark_case_contamination"})
                continue
            corrected = candidate["corrected"]
            if corrected is None:
                excluded.append(review_id)
                audit.append({"review_id": review_id, "decision": "excluded", "reason": "missing_correction"})
                continue
            context = candidate["context"]
            example_content = {
                "messages": [
                    {"role": "system", "content": context["prompt"]},
                    {"role": "user", "content": context["query"]},
                    {"role": "assistant", "content": canonical_json(corrected)},
                ]
            }
            content_hash = sha256_json(example_content)
            if content_hash in seen:
                excluded.append(review_id)
                audit.append({"review_id": review_id, "decision": "excluded", "reason": "exact_duplicate"})
                continue
            seen.add(content_hash)
            split = self._split(content_hash, split_seed)
            example = {
                "example_id": content_hash,
                "split": split,
                **example_content,
                "provenance": {
                    "review_id": review_id,
                    "run_id": candidate["run_id"],
                    "case_id": candidate["case_id"],
                    "snapshot_id": candidate["snapshot_id"],
                    "strategy_id": context["strategy_id"],
                    "model": context["model"],
                    "original_sha256": candidate["original_sha256"],
                    "corrected_sha256": candidate["corrected_sha256"],
                },
            }
            examples.append(example)
            exported.append(review_id)
            audit.append({"review_id": review_id, "decision": "included", "reason": "approved_unique_non_benchmark", "example_id": content_hash, "split": split})
        if not examples:
            raise DatasetError("no eligible approved examples remain after contamination and dedup checks")
        root.mkdir(parents=True, exist_ok=True)
        dataset_id = str(uuid.uuid4())
        staging = root / f".staging-dataset_{dataset_id}"
        final = root / f"dataset_{dataset_id}"
        staging.mkdir(exist_ok=False)
        examples.sort(key=lambda item: item["example_id"])
        payloads: dict[str, bytes] = {
            f"{split}.jsonl": _jsonl([item for item in examples if item["split"] == split])
            for split in SPLITS
        }
        payloads["audit.jsonl"] = _jsonl(audit)
        artifact_hashes = {name: _sha(data) for name, data in payloads.items()}
        fingerprint = sha256_json(
            {
                "format": DATASET_FORMAT,
                "examples": [item["example_id"] for item in examples],
                "split_seed_sha256": _sha(split_seed.encode("utf-8")),
                "benchmark_fingerprints": benchmark_hashes,
            }
        )
        manifest = {
            "format": DATASET_FORMAT,
            "dataset_id": dataset_id,
            "name": name,
            "fingerprint": fingerprint,
            "created_at": utc_timestamp(),
            "training_eligible": True,
            "split_seed_sha256": _sha(split_seed.encode("utf-8")),
            "benchmark_case_ids_excluded": sorted(blocked_cases),
            "benchmark_fingerprints": benchmark_hashes,
            "counts": {
                "included": len(examples), "excluded": len(excluded),
                **{split: sum(item["split"] == split for item in examples) for split in SPLITS},
            },
            "artifacts": artifact_hashes,
        }
        for filename, data in payloads.items():
            (staging / filename).write_bytes(data)
        (staging / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
        publish_directory(staging, final)
        DatasetVerifier().verify(final)
        return DatasetResult(final, dataset_id, fingerprint, tuple(exported), tuple(excluded))

    @staticmethod
    def _split(content_hash: str, seed: str) -> str:
        bucket = int(_sha((seed + content_hash).encode("utf-8"))[:8], 16) % 100
        return "train" if bucket < 80 else "validation" if bucket < 90 else "test"


class DatasetVerifier:
    def verify(self, path: Path) -> dict[str, Any]:
        root = path.resolve(strict=True)
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DatasetError("invalid dataset manifest") from error
        if manifest.get("format") != DATASET_FORMAT or manifest.get("training_eligible") is not True:
            raise DatasetError("invalid dataset format or eligibility")
        for filename, expected in manifest.get("artifacts", {}).items():
            if _sha((root / filename).read_bytes()) != expected:
                raise DatasetError(f"dataset artifact hash mismatch: {filename}")
        examples: list[dict[str, Any]] = []
        for split in SPLITS:
            for line in (root / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if item.get("split") != split:
                        raise DatasetError(f"example stored in the wrong split: {item.get('example_id')}")
                    examples.append(item)
        ids = [item["example_id"] for item in examples]
        if len(ids) != len(set(ids)) or len(ids) != manifest["counts"]["included"]:
            raise DatasetError("dataset deduplication or count invariant failed")
        expected_fingerprint = sha256_json(
            {
                "format": manifest["format"],
                "examples": sorted(ids),
                "split_seed_sha256": manifest["split_seed_sha256"],
                "benchmark_fingerprints": manifest["benchmark_fingerprints"],
            }
        )
        if expected_fingerprint != manifest.get("fingerprint"):
            raise DatasetError("dataset fingerprint mismatch")
        return manifest
