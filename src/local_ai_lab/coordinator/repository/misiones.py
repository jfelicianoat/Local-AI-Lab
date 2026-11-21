"""Persisted mission plans and explicit links to evidence."""
from __future__ import annotations

from typing import Any

from local_ai_lab.coordinator.repository.producto import ProductoMixin
from local_ai_lab.coordinator.repository.base import CoordinatorConflict
from local_ai_lab.domain.common import utc_timestamp


class MisionesMixin(ProductoMixin):
    def save_mission(self, *, mission_id: str, strategy: str, task: str,
                     success: str, constraints: str, teacher_source: str | None,
                     teacher_model: str | None, student_model: str | None,
                     expected_revision: int | None = None) -> None:
        now = utc_timestamp()
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM mission_plans WHERE mission_id=?", (mission_id,)).fetchone()
            if expected_revision is not None and expected_revision != (existing["revision"] if existing else 0):
                raise CoordinatorConflict("La misión cambió en otra sesión. Conserva tu borrador y revisa la versión guardada.")
            if existing and existing["strategy"] != strategy and db.execute(
                "SELECT 1 FROM mission_links WHERE mission_id=? LIMIT 1", (mission_id,)
            ).fetchone():
                raise ValueError("remove linked evidence before changing mission strategy")
            db.execute(
                """INSERT INTO mission_plans (mission_id, strategy, task, success, constraints_text,
                   teacher_source, teacher_model, student_model, created_at, updated_at, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(mission_id) DO UPDATE SET
                   strategy=excluded.strategy, task=excluded.task,
                   success=excluded.success, constraints_text=excluded.constraints_text,
                   teacher_source=excluded.teacher_source,
                   teacher_model=excluded.teacher_model,
                   student_model=excluded.student_model,
                   updated_at=excluded.updated_at, revision=mission_plans.revision+1""",
                (mission_id, strategy, task, success, constraints, teacher_source,
                 teacher_model, student_model, now, now),
            )

    def mission_plan(self, mission_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM mission_plans WHERE mission_id=?", (mission_id,)
            ).fetchone()
            if row is None:
                return None
            links = db.execute(
                """SELECT stage_index, reference_kind, reference_id, linked_at
                   FROM mission_links WHERE mission_id=?
                   ORDER BY stage_index, linked_at, reference_id""", (mission_id,)
            ).fetchall()
        return {
            "mission_id": row["mission_id"], "strategy": row["strategy"],
            "task": row["task"], "success": row["success"],
            "constraints": row["constraints_text"],
            "teacher_source": row["teacher_source"],
            "teacher_model": row["teacher_model"],
            "student_model": row["student_model"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "revision": row["revision"],
            "links": [dict(link) for link in links],
        }

    def mission_ids(self) -> list[str]:
        with self.connect() as db:
            return [row["mission_id"] for row in db.execute(
                "SELECT mission_id FROM mission_plans ORDER BY updated_at DESC, mission_id"
            )]

    def add_mission_link(self, mission_id: str, stage_index: int,
                         reference_kind: str, reference_id: str) -> None:
        now = utc_timestamp()
        with self.transaction() as db:
            db.execute(
                """INSERT OR IGNORE INTO mission_links VALUES (?, ?, ?, ?, ?)""",
                (mission_id, stage_index, reference_kind, reference_id, now),
            )
            db.execute("UPDATE mission_plans SET updated_at=? WHERE mission_id=?", (now, mission_id))

    def remove_mission_link(self, mission_id: str, stage_index: int,
                            reference_kind: str, reference_id: str) -> None:
        with self.transaction() as db:
            db.execute(
                """DELETE FROM mission_links WHERE mission_id=? AND stage_index=?
                   AND reference_kind=? AND reference_id=?""",
                (mission_id, stage_index, reference_kind, reference_id),
            )
            db.execute("UPDATE mission_plans SET updated_at=? WHERE mission_id=?",
                       (utc_timestamp(), mission_id))
