from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from local_ai_lab.knowledge_index.snapshot import SnapshotVerifier
from local_ai_lab.retrieval.engine import RetrievalCandidate


class BaseRetriever(Protocol):
    strategy_id: str

    def retrieve(self, query: str, *, limit: int = 10) -> list[RetrievalCandidate]: ...


@dataclass(frozen=True, slots=True)
class GraphExpansion:
    source_path: str
    target_path: str
    raw_target: str
    is_embed: bool
    source_rank: int
    contribution: float


@dataclass(frozen=True, slots=True)
class ContextBlock:
    chunk_id: str
    relative_path: str
    section: str
    content: str
    evidence_reference: str


@dataclass(frozen=True, slots=True)
class AssembledContext:
    blocks: tuple[ContextBlock, ...]
    rendered: str
    used_characters: int
    truncated: bool


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class GraphRetriever:
    strategy_id = "R4.hybrid-graph.v1"

    def __init__(
        self,
        snapshot: Path,
        base: BaseRetriever,
        *,
        neighbor_weight: float = 0.35,
        embed_weight: float = 1.25,
    ) -> None:
        if neighbor_weight <= 0 or embed_weight <= 0:
            raise ValueError("graph weights must be positive")
        verified = SnapshotVerifier().verify(snapshot)
        self.snapshot_hash = verified["manifest"]["global_hash"]
        self.base = base
        self.neighbor_weight = neighbor_weight
        self.embed_weight = embed_weight
        notes = _jsonl(snapshot / "notes.jsonl")
        chunks = _jsonl(snapshot / "chunks.jsonl")
        links = _jsonl(snapshot / "links.jsonl")
        self._chunks_by_path: dict[str, list[dict]] = {}
        for chunk in chunks:
            self._chunks_by_path.setdefault(chunk["relative_path"], []).append(chunk)
        self._paths = {note["relative_path"] for note in notes}
        self._case_paths = {path.casefold(): path for path in self._paths}
        self._by_stem: dict[str, list[str]] = {}
        for path in self._paths:
            self._by_stem.setdefault(PurePosixPath(path).stem.casefold(), []).append(path)
        self._edges: dict[str, list[tuple[str, str, bool]]] = {}
        for link in links:
            target = self._resolve(link["relative_path"], link["raw_target"])
            if target is None:
                continue
            source = link["relative_path"]
            self._edges.setdefault(source, []).append((target, link["raw_target"], link["is_embed"]))
            self._edges.setdefault(target, []).append((source, link["raw_target"], link["is_embed"]))
        self.last_trace: tuple[GraphExpansion, ...] = ()

    def retrieve(self, query: str, *, limit: int = 10) -> list[RetrievalCandidate]:
        seed_limit = min(100, max(limit * 2, limit))
        seeds = self.base.retrieve(query, limit=seed_limit)
        scores: dict[str, float] = {}
        candidates: dict[str, RetrievalCandidate] = {}
        trace: list[GraphExpansion] = []
        for seed in seeds:
            seed_score = 1.0 / seed.rank
            scores[seed.chunk_id] = max(scores.get(seed.chunk_id, 0.0), seed_score)
            candidates[seed.chunk_id] = seed
            for target, raw_target, is_embed in self._edges.get(seed.relative_path, []):
                edge_weight = self.neighbor_weight * (self.embed_weight if is_embed else 1.0)
                contribution = seed_score * edge_weight
                trace.append(
                    GraphExpansion(seed.relative_path, target, raw_target, is_embed, seed.rank, contribution)
                )
                for chunk in self._chunks_by_path.get(target, []):
                    chunk_id = chunk["chunk_id"]
                    scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution
                    candidates.setdefault(
                        chunk_id,
                        RetrievalCandidate(
                            chunk_id, chunk["note_id"], target, chunk["section"], chunk["content"],
                            contribution, 0, self.strategy_id,
                            f"snapshot:sha256:{self.snapshot_hash}#chunk:{chunk_id}",
                        ),
                    )
        ordered = sorted(candidates.values(), key=lambda item: (-scores[item.chunk_id], item.chunk_id))[:limit]
        self.last_trace = tuple(sorted(trace, key=lambda item: (-item.contribution, item.source_path, item.target_path)))
        return [
            RetrievalCandidate(
                item.chunk_id, item.note_id, item.relative_path, item.section, item.content,
                scores[item.chunk_id], rank, self.strategy_id, item.evidence_reference,
            )
            for rank, item in enumerate(ordered, start=1)
        ]

    def _resolve(self, source_path: str, raw_target: str) -> str | None:
        normalized = raw_target.replace("\\", "/").strip().removesuffix(".md") + ".md"
        source_relative = str(PurePosixPath(source_path).parent / normalized)
        for candidate in (source_relative, normalized):
            found = self._case_paths.get(candidate.casefold())
            if found:
                return found
        matches = self._by_stem.get(PurePosixPath(normalized).stem.casefold(), [])
        return matches[0] if len(matches) == 1 else None


class ContextAssembler:
    def assemble(
        self,
        candidates: list[RetrievalCandidate],
        *,
        max_characters: int,
        snapshot_id: str | None = None,
    ) -> AssembledContext:
        if max_characters < 1:
            raise ValueError("max_characters must be positive")
        blocks: list[ContextBlock] = []
        rendered_parts: list[str] = []
        used = 0
        seen: set[str] = set()
        truncated = False
        for item in candidates:
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            # El verificador determinista exige note_id y chunk_id en cada cita. Si el
            # bloque no los muestra, el modelo no puede producir una evidencia válida.
            # snapshot_id se repite en cada bloque a propósito: declararlo una sola vez
            # obliga al modelo a arrastrarlo de memoria y lo copia mal.
            snapshot_field = f" | snapshot_id={snapshot_id}" if snapshot_id else ""
            header = (
                f"[EVIDENCE source_reference={item.evidence_reference}"
                f"{snapshot_field}"
                f" | note_id={item.note_id}"
                f" | chunk_id={item.chunk_id}"
                f" | note_path={item.relative_path}"
                f" | section={item.section}]\n"
            )
            text = header + item.content + "\n"
            if used + len(text) > max_characters:
                truncated = True
                continue
            rendered_parts.append(text)
            used += len(text)
            blocks.append(
                ContextBlock(
                    item.chunk_id, item.relative_path, item.section, item.content,
                    item.evidence_reference,
                )
            )
        return AssembledContext(tuple(blocks), "\n".join(rendered_parts), used, truncated)
