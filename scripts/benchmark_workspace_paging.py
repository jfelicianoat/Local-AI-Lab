"""Measure bounded desktop workspace reads with a reproducible synthetic catalogue."""
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
from local_ai_lab.domain.common import canonical_json


def main() -> None:
    root = Path(__file__).resolve().parents[1] / ".audit-fix-tests"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="workspace-scale-", dir=root) as directory:
        target = Path(directory).resolve()
        if not target.is_relative_to(root.resolve()):
            raise RuntimeError("benchmark directory escaped its workspace root")
        service = CoordinatorService(target / "state.db")
        base = datetime(2026, 9, 29, tzinfo=UTC)
        rows = []
        for number in range(10_000):
            stamp = (base + timedelta(microseconds=number)).isoformat(timespec="microseconds").replace("+00:00", "Z")
            rows.append((
                f"scale-{number:05}", "experiment" if number % 2 else "dataset",
                f"Synthetic record {number}", "READY", "a" * 64,
                canonical_json({"number": number}), stamp, stamp,
            ))
        with service.repository.transaction() as db:
            db.executemany("INSERT INTO product_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

        tracemalloc.start()
        start = time.perf_counter()
        page = service.product_workspace_page()
        page_ms = round((time.perf_counter() - start) * 1000, 2)
        _, page_peak = tracemalloc.get_traced_memory()
        page_json_bytes = len(canonical_json(page).encode("utf-8"))
        tracemalloc.stop()
        tracemalloc.start()
        start = time.perf_counter()
        old = service.product_workspace()
        old_ms = round((time.perf_counter() - start) * 1000, 2)
        _, old_peak = tracemalloc.get_traced_memory()
        old_json_bytes = len(canonical_json(old).encode("utf-8"))
        tracemalloc.stop()
        assert len(page["experiments"]) == len(page["datasets"]) == 50
        assert len(old["experiments"]) == len(old["datasets"]) == 5_000
        print(json.dumps({
            "records": 10_000,
            "database_bytes": sum(file.stat().st_size for file in target.glob("state.db*")),
            "paged_initial_ms": page_ms,
            "paged_initial_json_bytes": page_json_bytes,
            "paged_initial_peak_python_bytes": page_peak,
            "old_full_ms": old_ms,
            "old_full_json_bytes": old_json_bytes,
            "old_full_peak_python_bytes": old_peak,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
