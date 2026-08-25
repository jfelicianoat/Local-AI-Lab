from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

from local_ai_lab.domain.common import publish_directory


def deterministic_zip(source_root: Path, target: Path) -> tuple[Path, str]:
    source = source_root.resolve(strict=True)
    destination = target.resolve()
    if not source.is_dir() or str(destination).startswith(("\\\\", "//")):
        raise ValueError("archive source and destination must be local")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return destination, _sha(destination)


def safe_extract_zip(source: Path, destination: Path) -> Path:
    archive_path = source.resolve(strict=True)
    target = destination.resolve()
    if target.exists() or str(target).startswith(("\\\\", "//")):
        raise ValueError("archive extraction requires a new local destination")
    staging = target.with_name(target.name + ".staging-" + os.urandom(6).hex())
    staging.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = (staging / member.filename).resolve()
            try:
                member_path.relative_to(staging)
            except ValueError as error:
                raise ValueError("archive member escapes extraction root") from error
            if member.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source_stream, member_path.open("xb") as output:
                while block := source_stream.read(1024 * 1024):
                    output.write(block)
        target.parent.mkdir(parents=True, exist_ok=True)
        publish_directory(staging, target)
    return target


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()
