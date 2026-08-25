from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from local_ai_lab.domain.common import canonical_json, utc_timestamp
from local_ai_lab.knowledge_index.snapshot import SnapshotError, SnapshotVerifier


@dataclass(frozen=True, slots=True)
class LexicalHit:
    chunk_id: str
    note_id: str
    relative_path: str
    section: str
    content: str
    score: float
    evidence_reference: str


SCHEMA = """
PRAGMA journal_mode=DELETE;
PRAGMA foreign_keys=ON;
CREATE TABLE build_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE notes(
  note_id TEXT PRIMARY KEY,
  relative_path TEXT NOT NULL UNIQUE,
  current_revision_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  frontmatter_json TEXT NOT NULL
);
CREATE TABLE revisions(
  revision_id TEXT NOT NULL,
  note_id TEXT NOT NULL REFERENCES notes(note_id),
  source_sha256 TEXT NOT NULL,
  PRIMARY KEY(revision_id, note_id)
);
CREATE TABLE chunks(
  chunk_id TEXT PRIMARY KEY,
  note_id TEXT NOT NULL REFERENCES notes(note_id),
  revision_id TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  locator TEXT NOT NULL,
  section TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  content TEXT NOT NULL
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  chunk_id UNINDEXED, content, section, relative_path,
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE links(
  link_id TEXT PRIMARY KEY,
  source_note_id TEXT NOT NULL REFERENCES notes(note_id),
  source_revision_id TEXT NOT NULL,
  raw_target TEXT NOT NULL,
  heading TEXT,
  is_embed INTEGER NOT NULL CHECK(is_embed IN (0, 1)),
  start_offset INTEGER NOT NULL,
  end_offset INTEGER NOT NULL
);
CREATE TABLE tags(
  note_id TEXT NOT NULL REFERENCES notes(note_id),
  tag TEXT NOT NULL,
  PRIMARY KEY(note_id, tag)
);
CREATE TABLE exclusions(rule_type TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(rule_type, value));
CREATE TABLE snapshot_errors(relative_path TEXT NOT NULL, reason TEXT NOT NULL);
CREATE INDEX chunks_note_idx ON chunks(note_id, ordinal);
CREATE INDEX links_source_idx ON links(source_note_id);
CREATE INDEX tags_value_idx ON tags(tag);
"""


def _records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise SnapshotError(f"invalid JSONL record in {path.name}:{line_number}")
            yield value


class KnowledgeIndexBuilder:
    """Creates a disposable local SQLite projection from a verified snapshot."""

    def build(
        self,
        snapshot: Path,
        database: Path,
        *,
        require_complete: bool = True,
        previous_database: Path | None = None,
    ) -> Path:
        verified = SnapshotVerifier().verify(snapshot)
        manifest = verified["manifest"]
        metadata = verified["metadata"]
        if require_complete and manifest["state"] != "COMPLETE":
            raise SnapshotError("an incomplete snapshot cannot back a complete knowledge index")
        target = database.resolve()
        if str(target).startswith(("\\\\", "//")):
            raise SnapshotError("knowledge index must be stored on a local filesystem")
        if target.exists():
            raise FileExistsError("refusing to replace an existing knowledge index")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.building")
        current_notes = list(_records(snapshot / "notes.jsonl"))
        previous_revisions: dict[str, str] = {}
        previous_snapshot_hash: str | None = None
        if previous_database is not None:
            previous = previous_database.resolve(strict=True)
            if str(previous).startswith(("\\\\", "//")):
                raise SnapshotError("previous knowledge index must be local")
            prior = sqlite3.connect(f"file:{previous.as_posix()}?mode=ro", uri=True)
            try:
                if prior.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SnapshotError("previous knowledge index failed integrity check")
                previous_revisions = dict(
                    prior.execute("SELECT relative_path, current_revision_id FROM notes").fetchall()
                )
                row = prior.execute(
                    "SELECT value FROM build_metadata WHERE key='snapshot_global_hash'"
                ).fetchone()
                previous_snapshot_hash = row[0] if row else None
            finally:
                prior.close()
        current_revisions = {
            note["relative_path"]: note["note_revision_id"] for note in current_notes
        }
        added = sorted(current_revisions.keys() - previous_revisions.keys())
        removed = sorted(previous_revisions.keys() - current_revisions.keys())
        unchanged = sorted(
            path for path in current_revisions.keys() & previous_revisions.keys()
            if current_revisions[path] == previous_revisions[path]
        )
        changed = sorted(
            path for path in current_revisions.keys() & previous_revisions.keys()
            if current_revisions[path] != previous_revisions[path]
        )
        incremental = {
            "mode": "generational_incremental" if previous_database is not None else "full",
            "previous_snapshot_hash": previous_snapshot_hash,
            "added": added, "changed": changed, "unchanged": unchanged, "removed": removed,
        }
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(SCHEMA)
            with connection:
                build_values = {
                    "schema_version": "knowledge-index.v1",
                    "snapshot_id": manifest["snapshot_id"],
                    "snapshot_global_hash": manifest["global_hash"],
                    "snapshot_state": manifest["state"],
                    "built_at": utc_timestamp(),
                    "source_snapshot": str(snapshot.resolve()),
                    "incremental_audit": canonical_json(incremental),
                }
                connection.executemany(
                    "INSERT INTO build_metadata(key, value) VALUES (?, ?)", build_values.items()
                )
                for note in current_notes:
                    connection.execute(
                        "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            note["note_id"], note["relative_path"], note["note_revision_id"],
                            note["source_sha256"], note["size"], canonical_json(note["frontmatter"]),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO revisions VALUES (?, ?, ?)",
                        (note["note_revision_id"], note["note_id"], note["source_sha256"]),
                    )
                    connection.executemany(
                        "INSERT INTO tags VALUES (?, ?)",
                        ((note["note_id"], tag) for tag in note["tags"]),
                    )
                for chunk in _records(snapshot / "chunks.jsonl"):
                    values = (
                        chunk["chunk_id"], chunk["note_id"], chunk["note_revision_id"],
                        chunk["relative_path"], chunk["locator"], chunk["section"],
                        chunk["ordinal"], chunk["content"],
                    )
                    connection.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
                    connection.execute(
                        "INSERT INTO chunks_fts(chunk_id, content, section, relative_path) VALUES (?, ?, ?, ?)",
                        (chunk["chunk_id"], chunk["content"], chunk["section"], chunk["relative_path"]),
                    )
                for link in _records(snapshot / "links.jsonl"):
                    connection.execute(
                        "INSERT INTO links VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            link["link_id"], link["source_note_id"], link["source_revision_id"],
                            link["raw_target"], link["heading"], int(link["is_embed"]),
                            link["start"], link["end"],
                        ),
                    )
                for rule_type, values in metadata["exclusions"].items():
                    connection.executemany(
                        "INSERT INTO exclusions VALUES (?, ?)", ((rule_type, value) for value in values)
                    )
                connection.executemany(
                    "INSERT INTO snapshot_errors VALUES (?, ?)",
                    ((hole["relative_path"], hole["reason"]) for hole in manifest["holes"]),
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise SnapshotError(f"knowledge index integrity failure: {integrity}")
        finally:
            connection.close()
        temporary.rename(target)
        return target


class KnowledgeIndex:
    def __init__(self, database: Path) -> None:
        self.database = database.resolve(strict=True)

    def search(self, query: str, *, limit: int = 10) -> list[LexicalHit]:
        if not query.strip() or limit < 1 or limit > 100:
            raise ValueError("query must be non-empty and limit must be between 1 and 100")
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        if not tokens:
            raise ValueError("query must contain searchable terms")
        fts_query = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                """
                SELECT c.chunk_id, c.note_id, c.relative_path, c.section, c.content, bm25(chunks_fts)
                FROM chunks_fts JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
                WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts), c.relative_path, c.ordinal LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            snapshot_hash = connection.execute(
                "SELECT value FROM build_metadata WHERE key='snapshot_global_hash'"
            ).fetchone()[0]
        finally:
            connection.close()
        return [
            LexicalHit(*row, evidence_reference=f"snapshot:sha256:{snapshot_hash}#chunk:{row[0]}")
            for row in rows
        ]
