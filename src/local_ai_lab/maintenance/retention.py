"""Reviewed CAS cleanup, with conservative references and durable approval.

Product history is never a cleanup candidate. The only candidates are old
unreferenced blobs and old upload directories belonging to terminal jobs (or
local ingests). Approval retires upload identities before deleting any files,
so replayed transport responses cannot resurrect a removed artifact.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from local_ai_lab.coordinator.repository.base import CoordinatorConflict
from local_ai_lab.domain.common import canonical_json, new_id, utc_timestamp


_DIGEST = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
_TERMINAL = {"succeeded", "failed", "cancelled", "superseded"}
_INTERNAL = {"idempotency", "artifact_upload_owners", "storage_cleanup_plans",
             "retired_artifact_uploads"}
_MAX_ENTRIES = 200


def _references(db: Any) -> tuple[set[str], dict[str, dict[str, Any]]]:
    protected: set[str] = set()
    # Include every application table, including feedback, events and evidence.
    # Transport caches and cleanup records are not product references.
    tables = [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    for table in tables:
        if table in _INTERNAL:
            continue
        quoted = '"' + table.replace('"', '""') + '"'
        for row in db.execute(f"SELECT * FROM {quoted}"):
            for value in row:
                if isinstance(value, str):
                    protected.update(match.lower() for match in _DIGEST.findall(value))
    owners = {row["artifact_id"]: dict(row) for row in db.execute(
        "SELECT a.*, j.state FROM artifact_upload_owners a LEFT JOIN jobs j USING(job_id)"
    )}
    for owner in owners.values():
        if owner["state"] not in _TERMINAL:
            protected.add(owner["sha256"])
    return protected, owners


def _inventory(path: Path, *, directory: bool) -> tuple[int, int, str]:
    """Stat a bounded tree without traversing links or leaving its root."""
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("linked storage entry cannot be cleaned")
    files = []
    pending = [path]
    count = 0
    while pending:
        item = pending.pop()
        count += 1
        if count > 10000 or item.is_symlink() or item.resolve() != item:
            raise ValueError("unsafe or oversized storage entry")
        stat = item.stat()
        files.append((item.relative_to(path).as_posix(), stat.st_size, stat.st_mtime_ns,
                      item.is_dir()))
        if item.is_dir():
            pending.extend(item.iterdir())
        elif not item.is_file():
            raise ValueError("unsupported storage entry")
    if path.is_dir() != directory:
        raise ValueError("storage entry type changed")
    size = sum(size for _, size, _, is_dir in files if not is_dir)
    latest = max(modified for _, _, modified, _ in files)
    fingerprint = hashlib.sha256(canonical_json(sorted(files)).encode()).hexdigest()
    return size, latest, fingerprint


def _candidates(store: Any, db: Any, cutoff: datetime) -> list[dict[str, Any]]:
    protected, owners = _references(db)
    uploads = []
    cutoff_ns = int(cutoff.timestamp() * 1_000_000_000)
    # Recent uploads protect their digest even after commit, during the interval
    # between ingestion and publication of the durable product reference.
    for directory in sorted(store.uploads.iterdir()):
        if not directory.is_dir():
            continue
        try:
            manifest = store._manifest(directory.name)
            size, latest, fingerprint = _inventory(directory, directory=True)
            created = datetime.fromisoformat(manifest.created_at.replace("Z", "+00:00"))
            owner = owners.get(directory.name)
            old = latest <= cutoff_ns and created <= cutoff
            inactive = owner is None or owner["state"] in _TERMINAL
            if not old or not inactive:
                protected.add(manifest.expected_sha256)
                continue
            uploads.append({"kind": "upload", "id": directory.name,
                            "sha256": manifest.expected_sha256, "bytes": size,
                            "last_activity": datetime.fromtimestamp(latest / 1e9, UTC).isoformat(),
                            "fingerprint": fingerprint,
                            "source_job_id": owner["job_id"] if owner else None})
        except (OSError, ValueError, TypeError):
            # Unknown/corrupt directories require investigation; never delete them.
            # If their manifest is readable, still retain its referenced blob.
            try:
                protected.add(store._manifest(directory.name).expected_sha256)
            except (OSError, ValueError, TypeError):
                pass
    blobs = []
    for prefix in sorted(store.blobs.iterdir()):
        if not prefix.is_dir() or prefix.is_symlink() or prefix.resolve() != prefix:
            continue
        for path in sorted(prefix.iterdir()):
            digest = path.name
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in protected:
                continue
            try:
                if store.blob_path(digest) != path:
                    continue
                size, latest, fingerprint = _inventory(path, directory=False)
                if latest <= cutoff_ns:
                    blobs.append({"kind": "blob", "id": digest, "sha256": digest,
                                  "bytes": size, "fingerprint": fingerprint,
                                  "last_activity": datetime.fromtimestamp(latest / 1e9, UTC).isoformat(),
                                  "source_job_id": None})
            except (OSError, ValueError):
                continue
    return uploads + blobs


def create_cleanup_plan(store: Any, repository: Any, older_than_days: int) -> dict[str, Any]:
    if type(older_than_days) is not int or not 7 <= older_than_days <= 365:
        raise ValueError("retention must be between 7 and 365 days")
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    with store.maintenance_lock(), repository.transaction() as db:
        pending = pending_cleanup_plan(repository, db=db)
        if pending:
            return pending
        candidates = _candidates(store, db, cutoff)
        selected = candidates[:_MAX_ENTRIES]
        plan = {"plan_id": new_id(), "older_than_days": older_than_days,
                "cutoff": cutoff.isoformat(), "created_at": utc_timestamp(),
                "entries": selected, "reclaimable_bytes": sum(item["bytes"] for item in selected),
                "remaining_count": max(0, len(candidates) - len(selected))}
        db.execute("INSERT INTO storage_cleanup_plans VALUES (?, ?, 'review', NULL, ?)",
                   (plan["plan_id"], canonical_json(plan), plan["created_at"]))
        return plan


def pending_cleanup_plan(repository: Any, *, db: Any = None) -> dict[str, Any] | None:
    if db is None:
        with repository.connect() as connection:
            return pending_cleanup_plan(repository, db=connection)
    row = db.execute("SELECT plan_json FROM storage_cleanup_plans WHERE status='applying' "
                     "ORDER BY created_at LIMIT 1").fetchone()
    return {**json.loads(row["plan_json"]), "status": "applying"} if row else None


def apply_cleanup_plan(store: Any, repository: Any, plan_id: str) -> dict[str, Any]:
    with store.maintenance_lock():
        with repository.transaction() as db:
            row = db.execute("SELECT * FROM storage_cleanup_plans WHERE plan_id=?", (plan_id,)).fetchone()
            if row is None:
                raise KeyError("cleanup plan does not exist")
            if row["status"] == "applied":
                return json.loads(row["result_json"])
            plan = json.loads(row["plan_json"])
            trash_root = store.root / "cleanup-trash"
            trash = trash_root / plan["plan_id"]
            if trash_root.resolve() != trash_root or trash.resolve() != trash:
                raise ValueError("cleanup staging directory must not be linked")
            cutoff = datetime.fromisoformat(plan["cutoff"])
            current = {(item["kind"], item["id"]): item for item in _candidates(store, db, cutoff)}
            if row["status"] == "review":
                other = pending_cleanup_plan(repository, db=db)
                if other and other["plan_id"] != plan_id:
                    raise CoordinatorConflict("Completa primero la limpieza pendiente.")
                created = datetime.fromisoformat(plan["created_at"].replace("Z", "+00:00"))
                if datetime.now(UTC) - created > timedelta(hours=24):
                    raise CoordinatorConflict("La propuesta ha caducado. Revisa una nueva limpieza.")
                for item in plan["entries"]:
                    candidate = current.get((item["kind"], item["id"]))
                    if candidate is None or candidate["fingerprint"] != item["fingerprint"]:
                        raise CoordinatorConflict("El almacenamiento ha cambiado. Revisa una nueva limpieza.")
                # Commit approval and retirement BEFORE destructive file operations.
                # A crash can resume this exact decision without replaying old uploads.
                db.execute("UPDATE storage_cleanup_plans SET status='applying' WHERE plan_id=?", (plan_id,))
                for item in plan["entries"]:
                    if item["kind"] == "upload":
                        db.execute("INSERT OR IGNORE INTO retired_artifact_uploads VALUES (?, ?, ?)",
                                   (item["id"], plan_id, utc_timestamp()))
        with repository.transaction() as db:
            # Hold a write transaction throughout deletion: published references
            # cannot change between this second check and the filesystem operation.
            current = {(item["kind"], item["id"]): item for item in _candidates(store, db, cutoff)}
            protected, _ = _references(db)
            removed = skipped = 0
            for item in plan["entries"]:
                path = (store._upload_dir(item["id"]) if item["kind"] == "upload"
                        else store.blob_path(item["id"]))
                staged = trash / (item["kind"] + "-" + item["id"])
                if not path.exists() and not staged.exists():
                    removed += 1
                    continue
                if not staged.exists():
                    candidate = current.get((item["kind"], item["id"]))
                    if candidate is None or candidate["fingerprint"] != item["fingerprint"]:
                        skipped += 1
                        continue
                    trash.mkdir(parents=True, exist_ok=True)
                    # Atomic rename makes an interrupted directory deletion resumable.
                    path.replace(staged)
                if item["kind"] == "blob" and item["sha256"] in protected:
                    _inventory(staged, directory=False)
                    if not path.exists():
                        staged.replace(path)
                    skipped += 1
                    continue
                _inventory(staged, directory=item["kind"] == "upload")
                if item["kind"] == "upload":
                    shutil.rmtree(staged)
                else:
                    staged.unlink()
                removed += 1
            if trash.exists() and not any(trash.iterdir()):
                trash.rmdir()
            result = {"plan_id": plan_id, "status": "applied", "removed_count": removed,
                      "skipped_count": skipped, "completed_at": utc_timestamp()}
            db.execute("UPDATE storage_cleanup_plans SET status='applied', result_json=? WHERE plan_id=?",
                       (canonical_json(result), plan_id))
            return result
