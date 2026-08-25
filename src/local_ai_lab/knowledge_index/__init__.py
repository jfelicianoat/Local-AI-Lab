"""Regenerable read-only projection of immutable vault snapshots."""

from local_ai_lab.knowledge_index.projection import KnowledgeIndex, KnowledgeIndexBuilder
from local_ai_lab.knowledge_index.snapshot import SnapshotBuilder, SnapshotVerifier
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter

__all__ = [
    "KnowledgeIndex",
    "KnowledgeIndexBuilder",
    "ReadOnlyVaultAdapter",
    "SnapshotBuilder",
    "SnapshotVerifier",
]
