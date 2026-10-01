"""Measure first-page reads for 10,000 synthetic jobs and reviews."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_lab.coordinator.service import CoordinatorService


def measure(operation):
    tracemalloc.start()
    started = time.perf_counter()
    payload = operation()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return payload, {"elapsed_ms": elapsed_ms, "peak_python_bytes": peak,
                     "json_bytes": len(json.dumps(payload).encode("utf-8"))}


def main() -> None:
    root = Path(__file__).resolve().parents[1] / ".audit-fix-tests"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="history-scale-", dir=root) as directory:
        target = Path(directory).resolve()
        if not target.is_relative_to(root.resolve()):
            raise RuntimeError("benchmark directory escaped its workspace root")
        service = CoordinatorService(target / "state.db")
        base = datetime(2026, 9, 29, tzinfo=UTC)
        stamps = [(base + timedelta(microseconds=number)).isoformat(timespec="microseconds").replace("+00:00", "Z")
                  for number in range(10_000)]
        with service.repository.transaction() as db:
            db.executemany(
                "INSERT INTO jobs(job_id,spec_json,spec_fingerprint,state,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ((f"job-{number:05}", '{"kind":"test","correlation_id":"scale"}', "test", "READY", stamp, stamp)
                 for number, stamp in enumerate(stamps)),
            )
        with service.feedback.store.transaction() as db:
            db.executemany(
                "INSERT INTO reviews(review_id,run_id,case_id,snapshot_id,reviewer,status,training_state,context_json,original_json,original_sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ((f"review-{number:05}", f"run-{number:05}", "case", "snapshot", "tester", "draft", "excluded", "{}", "{}", "test", stamp, stamp)
                 for number, stamp in enumerate(stamps)),
            )
        jobs, job_stats = measure(service.jobs_page)
        reviews, review_stats = measure(service.reviews_page)
        overview, overview_stats = measure(service.overview)
        assert len(jobs["items"]) == len(reviews["items"]) == 50
        assert jobs["pagination"]["total"] == reviews["pagination"]["total"] == 10_000
        assert overview["job_counts"]["READY"] == 10_000
        print(json.dumps({"records_per_group": 10_000,
                          "database_bytes": sum(file.stat().st_size for file in target.glob("state.db*")),
                          "jobs_page": job_stats, "reviews_page": review_stats,
                          "overview": overview_stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
