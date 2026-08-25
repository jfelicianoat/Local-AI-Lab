from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Sequence

from local_ai_lab.domain.common import canonical_json, utc_timestamp
from local_ai_lab.storage.sqlite import ensure_local_database_path


def _tree_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(str(path.stat().st_size).encode("ascii"))
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
    return digest.hexdigest()


class SentenceTransformerEmbeddingProvider:
    provider_id = "sentence-transformers.local.v1"

    def __init__(self, model_path: Path, *, device: str = "cpu") -> None:
        self.model_path = model_path.resolve(strict=True)
        if not self.model_path.is_dir():
            raise ValueError("embedding model path must be a local directory")
        self.device = device
        self.model_fingerprint = _tree_fingerprint(self.model_path)
        self._model = None

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise RuntimeError("sentence-transformers is not installed on this worker") from error
            self._model = SentenceTransformer(
                str(self.model_path), device=self.device, local_files_only=True,
            )
        vectors = self._model.encode(
            list(texts), convert_to_numpy=True, normalize_embeddings=False,
            show_progress_bar=False,
        )
        return vectors.tolist()


class CachedEmbeddingProvider:
    provider_id = "local-ai-lab.cached-embeddings.v1"

    def __init__(self, delegate, database: Path) -> None:
        self.delegate = delegate
        self.database = ensure_local_database_path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.model_fingerprint = delegate.model_fingerprint
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS embeddings(
                   model_fingerprint TEXT NOT NULL, text_sha256 TEXT NOT NULL,
                   vector_json TEXT NOT NULL, created_at TEXT NOT NULL,
                   PRIMARY KEY(model_fingerprint, text_sha256))"""
            )
            connection.commit()
        finally:
            connection.close()

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        keys = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        connection = sqlite3.connect(self.database)
        try:
            cached: dict[str, list[float]] = {}
            for key in set(keys):
                row = connection.execute(
                    "SELECT vector_json FROM embeddings WHERE model_fingerprint=? AND text_sha256=?",
                    (self.model_fingerprint, key),
                ).fetchone()
                if row:
                    cached[key] = json.loads(row[0])
            missing_keys: list[str] = []
            missing_texts: list[str] = []
            for key, text in zip(keys, texts):
                if key not in cached and key not in missing_keys:
                    missing_keys.append(key)
                    missing_texts.append(text)
            if missing_texts:
                vectors = self.delegate.embed(missing_texts)
                if len(vectors) != len(missing_texts):
                    raise ValueError("embedding delegate returned the wrong vector count")
                with connection:
                    for key, vector in zip(missing_keys, vectors):
                        values = [float(value) for value in vector]
                        cached[key] = values
                        connection.execute(
                            "INSERT OR IGNORE INTO embeddings VALUES (?, ?, ?, ?)",
                            (self.model_fingerprint, key, canonical_json(values), utc_timestamp()),
                        )
            return [cached[key] for key in keys]
        finally:
            connection.close()
