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


FORMAT = "local-ai-lab.backup.v1"
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
                manifest = {"format": FORMAT, "database": database.name, "files": entries}
                output.writestr("manifest.json", json.dumps(manifest, sort_keys=True, ensure_ascii=False))
            os.replace(pending, archive)
        finally:
            pending.unlink(missing_ok=True)
    return manifest


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    if archive.namelist().count("manifest.json") != 1:
        raise ValueError("backup has no unique manifest")
    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("format") != FORMAT or not isinstance(manifest.get("files"), list):
        raise ValueError("unsupported backup format")
    listed: set[str] = set()
    for item in manifest["files"]:
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


def restore_backup(path: Path, target: Path) -> dict:
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
    args = parser.parse_args()
    if args.operation == "backup":
        manifest = create_backup(args.database, args.archive)
    elif args.operation == "verify":
        manifest = verify_backup(args.archive)
    else:
        manifest = restore_backup(args.archive, args.target)
    print(f"{args.operation}: {len(manifest['files'])} files verified")


if __name__ == "__main__":
    main()
