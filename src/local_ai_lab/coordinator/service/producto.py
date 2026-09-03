"""Espacio de producto: vision general, evidencias de fase y revisiones.

Es la capa que mira el humano: que hay hecho, que esta pendiente de
revisar y que correcciones se han aplicado.
"""
from __future__ import annotations

from typing import Any

from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.coordinator.service.base import ServicioBase


class ProductoMixin(ServicioBase):
    """Espacio de producto: vision general, evidencias de fase y revisiones."""

    def create_pairing_code(self, valid_seconds: int = 300) -> str:
        return self.repository.create_pairing_code(valid_seconds)

    def overview(self) -> dict[str, Any]:
        return self.repository.overview()

    def record_phase_evidence(self, **evidence: Any) -> dict[str, Any]:
        return self.repository.record_phase_evidence(**evidence)

    def product_workspace(self) -> dict[str, Any]:
        return self.repository.product_workspace()

    def jobs(self) -> list[dict[str, Any]]:
        return self.repository.jobs_view()

    def record_product_item(self, **item: Any) -> dict[str, Any]:
        return self.repository.record_product_item(**item)

    def reviews(self) -> list[dict[str, Any]]:
        return self.feedback.list_reviews()

    def save_review_correction(
        self, *, review_id: str, actor: str, corrected_response: dict[str, Any]
    ) -> dict[str, Any]:
        review = self.feedback.get(review_id)
        snapshot = self.repository.artifact_location(
            review["snapshot_id"], expected_kind="vault_snapshot"
        )
        return self.feedback.save_correction(
            review_id, actor=actor, corrected_response=corrected_response,
            verifier=ResearchResponseVerifier(snapshot),
        )

    def transition_review(self, *, review_id: str, to_state: str, actor: str) -> dict[str, Any]:
        return self.feedback.transition_review(review_id, to_state=to_state, actor=actor)

    def transition_training_candidate(
        self, *, review_id: str, to_state: str, actor: str
    ) -> dict[str, Any]:
        return self.feedback.transition_training(review_id, to_state=to_state, actor=actor)
