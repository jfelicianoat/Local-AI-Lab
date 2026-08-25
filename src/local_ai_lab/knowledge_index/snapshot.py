from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from local_ai_lab.domain.common import (
    canonical_json, publish_directory, sha256_json, sha256_text, utc_timestamp,
)
from local_ai_lab.knowledge_index.markdown import (
    CHUNKER_VERSION,
    PARSER_VERSION,
    chunk_identity,
    parse_markdown,
)
from local_ai_lab.knowledge_index.vault import VaultEntry

SNAPSHOT_FORMAT = "vault-snapshot.v1"
INCLUSION_POLICY = "markdown-only.v1"
RECORD_FILES = ("notes.jsonl", "chunks.jsonl", "links.jsonl")


class SnapshotError(RuntimeError):
    pass


class VaultReader(Protocol):
    vault_root: Path
    exclusions: Any

    def entries(self) -> list[VaultEntry]: ...

    def open_binary(self, relative_path: str): ...

    def stat(self, relative_path: str) -> VaultEntry: ...


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    path: Path
    snapshot_id: str
    global_hash: str
    state: str
    holes: tuple[dict[str, str], ...]


def _local_root(path: Path) -> Path:
    absolute = path.resolve()
    if str(absolute).startswith(("\\\\", "//")):
        raise SnapshotError("snapshot output must be on a local filesystem, not UNC")
    absolute.mkdir(parents=True, exist_ok=True)
    return absolute


def _entry_key(entry: VaultEntry) -> tuple[str, int, int]:
    return entry.relative_path, entry.size, entry.modified_ns


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return ("".join(canonical_json(record) + "\n" for record in records)).encode("utf-8")


def _decode_note(raw: bytes) -> tuple[str, str, bool]:
    """Decodifica una nota conservando el texto y declarando qué codificación se usó.

    Un vault real de Windows mezcla notas UTF-8 con notas cp1252 heredadas. Decodificar
    todo como UTF-8 con `errors="replace"` no falla: convierte cada acento de esas notas
    en U+FFFD sin avisar. El snapshot deja entonces de representar el vault, el índice
    léxico se construye sobre texto roto y ninguna cita puede coincidir con la fuente.

    El hash del snapshot se calcula sobre los bytes originales, así que la identidad no
    depende de esta decisión; solo la proyección de texto. Si ninguna codificación sirve
    se degrada a UTF-8 con reemplazo, pero se marca como pérdida para que quede registrada.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8"), "utf-8-sig", False
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding, False
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8/replace", True


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SnapshotBuilder:
    """Builds a local immutable snapshot without exposing vault mutation operations."""

    def __init__(self, *, file_retries: int = 2, listing_retries: int = 2) -> None:
        if file_retries < 0 or listing_retries < 0:
            raise ValueError("retry counts cannot be negative")
        self.file_retries = file_retries
        self.listing_retries = listing_retries

    def build(self, reader: VaultReader, output_root: Path, *, vault_id: str | None = None) -> SnapshotResult:
        root = _local_root(output_root)
        snapshot_id = str(uuid.uuid4())
        staging = root / f".staging-vault_snapshot_{snapshot_id}"
        final = root / f"vault_snapshot_{snapshot_id}"
        staging.mkdir(exist_ok=False)
        objects_root = staging / "objects" / "sha256"
        objects_root.mkdir(parents=True)
        effective_vault_id = vault_id or str(uuid.uuid5(uuid.NAMESPACE_URL, str(reader.vault_root).casefold()))
        try:
            vault_namespace = uuid.UUID(effective_vault_id)
        except ValueError as error:
            raise ValueError("vault_id must be a UUID") from error
        holes: list[dict[str, str]] = []
        captured: list[tuple[VaultEntry, bytes, str]] = []
        stable_listing: list[VaultEntry] = []

        for listing_attempt in range(self.listing_retries + 1):
            first = reader.entries()
            captured = []
            holes = []
            for entry in first:
                item = self._capture_stable(reader, entry)
                if item is None:
                    holes.append({"relative_path": entry.relative_path, "reason": "file_changed_while_reading"})
                else:
                    captured.append(item)
            second = reader.entries()
            if [_entry_key(item) for item in first] == [_entry_key(item) for item in second]:
                stable_listing = second
                break
            if listing_attempt == self.listing_retries:
                stable_listing = second
                holes.append({"relative_path": "*", "reason": "vault_listing_did_not_converge"})

        captured_by_path = {entry.relative_path: (entry, data, digest) for entry, data, digest in captured}
        expected_paths = {entry.relative_path for entry in stable_listing}
        for missing in sorted(expected_paths - captured_by_path.keys(), key=str.casefold):
            if not any(hole["relative_path"] == missing for hole in holes):
                holes.append({"relative_path": missing, "reason": "not_captured_from_stable_listing"})

        notes: list[dict[str, Any]] = []
        chunks: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        source_hashes: list[dict[str, Any]] = []
        for relative_path in sorted(expected_paths & captured_by_path.keys(), key=str.casefold):
            entry, raw, source_digest = captured_by_path[relative_path]
            object_path = objects_root / source_digest[:2] / source_digest
            object_path.parent.mkdir(parents=True, exist_ok=True)
            if not object_path.exists():
                object_path.write_bytes(raw)
            note_id = str(uuid.uuid5(vault_namespace, relative_path.casefold()))
            revision_id = source_digest
            text, encoding, lossy = _decode_note(raw)
            if lossy:
                holes.append({"relative_path": relative_path, "reason": "undecodable_bytes_replaced"})
            parsed = parse_markdown(text)
            notes.append(
                {
                    "note_id": note_id,
                    "note_revision_id": revision_id,
                    "relative_path": relative_path,
                    "source_sha256": source_digest,
                    "size": entry.size,
                    "text_encoding": encoding,
                    "frontmatter": parsed.frontmatter,
                    "tags": list(parsed.tags),
                }
            )
            for chunk in parsed.chunks:
                chunks.append(
                    {
                        "chunk_id": chunk_identity(revision_id, chunk),
                        "note_id": note_id,
                        "note_revision_id": revision_id,
                        "relative_path": relative_path,
                        "locator": chunk.locator,
                        "section": chunk.section,
                        "ordinal": chunk.ordinal,
                        "content": chunk.content,
                    }
                )
            for link in parsed.links:
                links.append(
                    {
                        "link_id": sha256_text(f"{note_id}\0{link.raw_target}\0{link.start}:{link.end}"),
                        "source_note_id": note_id,
                        "source_revision_id": revision_id,
                        "relative_path": relative_path,
                        "raw_target": link.raw_target,
                        "heading": link.heading,
                        "is_embed": link.is_embed,
                        "start": link.start,
                        "end": link.end,
                    }
                )
            source_hashes.append(
                {
                    "relative_path": relative_path,
                    "type": "file",
                    "size": entry.size,
                    "source_sha256": source_digest,
                    "inclusion_policy": INCLUSION_POLICY,
                }
            )

        notes.sort(key=lambda item: item["relative_path"].casefold())
        chunks.sort(key=lambda item: (item["relative_path"].casefold(), item["ordinal"]))
        links.sort(key=lambda item: (item["relative_path"].casefold(), item["start"]))
        global_hash = sha256_json(source_hashes)
        state = "COMPLETE" if not holes else "INCOMPLETE"
        created_at = utc_timestamp()
        metadata = {
            "format": SNAPSHOT_FORMAT,
            "snapshot_id": snapshot_id,
            "vault_id": effective_vault_id,
            "vault_name": reader.vault_root.name,
            "created_at": created_at,
            "parser_version": PARSER_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "inclusion_policy": INCLUSION_POLICY,
            "exclusions": reader.exclusions.as_dict(),
        }
        payloads = {
            "metadata.json": (canonical_json(metadata) + "\n").encode("utf-8"),
            "notes.jsonl": _jsonl(notes),
            "chunks.jsonl": _jsonl(chunks),
            "links.jsonl": _jsonl(links),
        }
        artifact_hashes = {name: _digest(data) for name, data in payloads.items()}
        hashes = {
            "global_hash": global_hash,
            "sources": source_hashes,
            "artifacts": artifact_hashes,
        }
        manifest = {
            "format": SNAPSHOT_FORMAT,
            "snapshot_id": snapshot_id,
            "state": state,
            "global_hash": global_hash,
            "created_at": created_at,
            "counts": {"notes": len(notes), "chunks": len(chunks), "links": len(links), "holes": len(holes)},
            "holes": holes,
        }
        for name, data in payloads.items():
            (staging / name).write_bytes(data)
        (staging / "hashes.json").write_text(canonical_json(hashes) + "\n", encoding="utf-8", newline="\n")
        (staging / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")
        publish_directory(staging, final)
        SnapshotVerifier().verify(final)
        self._make_read_only(final)
        return SnapshotResult(final, snapshot_id, global_hash, state, tuple(holes))

    def _capture_stable(self, reader: VaultReader, expected: VaultEntry) -> tuple[VaultEntry, bytes, str] | None:
        current = expected
        for _ in range(self.file_retries + 1):
            digest = hashlib.sha256()
            parts: list[bytes] = []
            try:
                with reader.open_binary(current.relative_path) as source:
                    while block := source.read(1024 * 1024):
                        digest.update(block)
                        parts.append(block)
                after = reader.stat(current.relative_path)
            except OSError:
                return None
            if _entry_key(current) == _entry_key(after) and sum(map(len, parts)) == after.size:
                return after, b"".join(parts), digest.hexdigest()
            current = after
        return None

    @staticmethod
    def _make_read_only(root: Path) -> None:
        for path in sorted(root.rglob("*"), reverse=True):
            try:
                path.chmod(0o555 if path.is_dir() else 0o444)
            except OSError:
                pass
        try:
            root.chmod(0o555)
        except OSError:
            pass


class SnapshotVerifier:
    def verify(self, snapshot: Path) -> dict[str, Any]:
        root = snapshot.resolve(strict=True)
        manifest = self._load_json(root / "manifest.json")
        metadata = self._load_json(root / "metadata.json")
        hashes = self._load_json(root / "hashes.json")
        if manifest.get("format") != SNAPSHOT_FORMAT or metadata.get("format") != SNAPSHOT_FORMAT:
            raise SnapshotError("unsupported snapshot format")
        if manifest.get("snapshot_id") != metadata.get("snapshot_id"):
            raise SnapshotError("snapshot identity mismatch")
        holes = manifest.get("holes")
        counts = manifest.get("counts")
        if not isinstance(holes, list) or not isinstance(counts, dict) or counts.get("holes") != len(holes):
            raise SnapshotError("manifest hole count mismatch")
        expected_state = "COMPLETE" if not holes else "INCOMPLETE"
        if manifest.get("state") != expected_state:
            raise SnapshotError("manifest state does not match its holes")
        for name, expected in hashes.get("artifacts", {}).items():
            actual = _digest((root / name).read_bytes())
            if actual != expected:
                raise SnapshotError(f"artifact hash mismatch: {name}")
        sources = hashes.get("sources", [])
        if sha256_json(sources) != hashes.get("global_hash") or manifest.get("global_hash") != hashes.get("global_hash"):
            raise SnapshotError("global hash mismatch")
        for source in sources:
            digest = source["source_sha256"]
            object_path = root / "objects" / "sha256" / digest[:2] / digest
            if not object_path.is_file() or _digest(object_path.read_bytes()) != digest:
                raise SnapshotError(f"source object hash mismatch: {source['relative_path']}")
        return {"manifest": manifest, "metadata": metadata, "hashes": hashes}

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SnapshotError(f"invalid snapshot file: {path.name}") from error
        if not isinstance(value, dict):
            raise SnapshotError(f"snapshot file must contain an object: {path.name}")
        return value
