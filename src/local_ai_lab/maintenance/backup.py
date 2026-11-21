"""Verified, offline backup and restore of the Coordinator data directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath


FORMAT = "local-ai-lab.backup.v2"
LEGACY_FORMAT = "local-ai-lab.backup.v1"
CHUNK = 1024 * 1024


def _copy_and_hash(source, destination) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while data := source.read(CHUNK):
        destination.write(data)
        digest.update(data)
        size += len(data)
    return digest.hexdigest(), size


def create_backup(database: Path, archive: Path) -> dict:
    """The caller must stop the Coordinator before copying external artifacts."""
    database = database.resolve(strict=True)
    root = database.parent
    archive = archive.resolve()
    if root == archive or root in archive.parents:
        raise ValueError("backup archive must be outside the Coordinator data directory")
    if database.is_symlink() or not database.is_file():
        raise ValueError("database must be a regular local file")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="local-ai-lab-backup-") as temporary:
        snapshot = Path(temporary) / "database.sqlite3"
        with closing(sqlite3.connect(database)) as live, closing(sqlite3.connect(snapshot)) as saved:
            live.backup(saved)
            integrity = saved.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError("database integrity check failed")
            locations = {}
            if saved.execute("SELECT 1 FROM sqlite_master WHERE name='artifact_locations'").fetchone():
                for record_id, local_path in saved.execute("SELECT record_id, local_path FROM artifact_locations"):
                    artifact = Path(local_path).resolve(strict=True)
                    if not artifact.is_relative_to(root):
                        raise ValueError(f"registered artifact outside backup data directory: {record_id}")
                    locations[record_id] = artifact.relative_to(root).as_posix()
        entries: list[dict[str, object]] = []
        pending = archive.with_name(f".{archive.name}.{os.getpid()}.partial")
        try:
            with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as output:
                for path in sorted(root.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"data directory contains a symlink: {path.relative_to(root)}")
                    if not path.is_file() or path == database or path.name in {
                        database.name + "-wal", database.name + "-shm",
                    }:
                        continue
                    relative = path.relative_to(root).as_posix()
                    with path.open("rb") as source, output.open(f"files/{relative}", "w", force_zip64=True) as target:
                        digest, size = _copy_and_hash(source, target)
                    entries.append({"path": relative, "sha256": digest, "size": size})
                with snapshot.open("rb") as source, output.open(f"files/{database.name}", "w", force_zip64=True) as target:
                    digest, size = _copy_and_hash(source, target)
                entries.append({"path": database.name, "sha256": digest, "size": size})
                manifest = {"format": FORMAT, "database": database.name, "files": entries,
                            "artifact_locations": locations}
                output.writestr("manifest.json", json.dumps(manifest, sort_keys=True, ensure_ascii=False))
            os.replace(pending, archive)
        finally:
            pending.unlink(missing_ok=True)
    return manifest


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    if archive.namelist().count("manifest.json") != 1:
        raise ValueError("backup has no unique manifest")
    manifest = json.loads(archive.read("manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("format") not in {FORMAT, LEGACY_FORMAT} or not isinstance(manifest.get("files"), list):
        raise ValueError("unsupported backup format")
    listed: set[str] = set()
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("backup contains an invalid entry")
        path = item.get("path")
        if not isinstance(path, str) or not path or path in listed:
            raise ValueError("backup contains a duplicate or invalid path")
        parts = PurePosixPath(path).parts
        if (path.startswith("/") or "\\" in path or ":" in path
                or path != PurePosixPath(path).as_posix()
                or any(part in {"", ".", ".."} for part in parts)):
            raise ValueError("backup contains an unsafe path")
        if not isinstance(item.get("size"), int) or item["size"] < 0:
            raise ValueError("backup has an invalid file size")
        digest = item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("backup has an invalid digest")
        listed.add(path)
    if manifest.get("database") not in listed:
        raise ValueError("backup omits the database")
    if set(archive.namelist()) != {"manifest.json"} | {f"files/{path}" for path in listed}:
        raise ValueError("backup contains unlisted files")
    if len(archive.namelist()) != len(listed) + 1:
        raise ValueError("backup contains duplicate archive members")
    if manifest["format"] == FORMAT:
        locations = manifest.get("artifact_locations")
        if not isinstance(locations, dict):
            raise ValueError("backup has no artifact relocation map")
        for record_id, relative in locations.items():
            if not isinstance(record_id, str) or not isinstance(relative, str) or not relative or (
                relative.startswith("/") or "\\" in relative or ":" in relative
                or relative != PurePosixPath(relative).as_posix()
                or any(part in {".", ".."} for part in PurePosixPath(relative).parts)
                or not any(path == relative or path.startswith(relative + "/") for path in listed)
            ):
                raise ValueError("backup has an unsafe or missing artifact relocation")
    return manifest


def verify_backup(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        manifest = _read_manifest(archive)
        for item in manifest["files"]:
            with archive.open(f"files/{item['path']}") as source:
                digest = hashlib.sha256()
                size = 0
                while data := source.read(CHUNK):
                    digest.update(data)
                    size += len(data)
            if size != item["size"] or digest.hexdigest() != item["sha256"]:
                raise ValueError(f"backup file failed verification: {item['path']}")
    return manifest


def restore_backup(path: Path, target: Path, *, original_root: Path | None = None) -> dict:
    target = target.resolve()
    if target.exists():
        raise FileExistsError("restore target must not exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = verify_backup(path)
    with tempfile.TemporaryDirectory(prefix="local-ai-lab-restore-", dir=target.parent) as temporary:
        staging = Path(temporary) / "data"
        staging.mkdir()
        with zipfile.ZipFile(path) as archive:
            for item in manifest["files"]:
                destination = staging.joinpath(*PurePosixPath(item["path"]).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(f"files/{item['path']}") as source, destination.open("xb") as output:
                    _copy_and_hash(source, output)
        with closing(sqlite3.connect(staging / manifest["database"])) as database:
            if database.execute("SELECT 1 FROM sqlite_master WHERE name='artifact_locations'").fetchone():
                rows = database.execute("SELECT record_id, local_path FROM artifact_locations").fetchall()
                locations = manifest.get("artifact_locations", {})
                if manifest["format"] == LEGACY_FORMAT and rows:
                    if original_root is None:
                        raise ValueError("legacy backup requires original_root to relocate artifact references")
                    root = original_root.resolve()
                    locations = {}
                    for record_id, local_path in rows:
                        original = Path(local_path)
                        if not original.is_absolute() or not original.is_relative_to(root):
                            raise ValueError("legacy backup references an artifact outside original_root")
                        locations[record_id] = original.relative_to(root).as_posix()
                if set(locations) != {record_id for record_id, _ in rows}:
                    raise ValueError("backup artifact map does not match the database")
                for record_id, _ in rows:
                    relative = PurePosixPath(locations[record_id])
                    restored_path = staging.joinpath(*relative.parts).resolve(strict=True)
                    if not restored_path.is_relative_to(staging):
                        raise ValueError("restored artifact escapes the data directory")
                    database.execute("UPDATE artifact_locations SET local_path=? WHERE record_id=?",
                                     (str(target.joinpath(*relative.parts)), record_id))
                database.commit()
            if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("restored database integrity check failed")
        staging.rename(target)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Copia verificable del Coordinator detenido")
    sub = parser.add_subparsers(dest="operation", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("database", type=Path)
    backup.add_argument("archive", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("archive", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("target", type=Path)
    restore.add_argument("--original-root", type=Path,
                         help="Original Coordinator directory, required for legacy v1 backups with artifacts")
    args = parser.parse_args()
    if args.operation == "backup":
        manifest = create_backup(args.database, args.archive)
    elif args.operation == "verify":
        manifest = verify_backup(args.archive)
    else:
        manifest = restore_backup(args.archive, args.target, original_root=args.original_root)
    print(f"{args.operation}: {len(manifest['files'])} files verified")


if __name__ == "__main__":
    main()
