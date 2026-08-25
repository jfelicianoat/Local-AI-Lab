from __future__ import annotations

import difflib
import json
import uuid
from pathlib import Path
from typing import Any

from local_ai_lab.domain.common import canonical_json, sha256_json, utc_timestamp
from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
from local_ai_lab.storage.sqlite import SQLiteStore

REVIEW_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"accepted", "rejected", "draft"},
    "accepted": set(),
    "rejected": {"draft"},
}
TRAINING_TRANSITIONS = {
    "excluded": {"proposed"},
    "proposed": {"approved", "rejected", "excluded"},
    "approved": {"exported", "rejected"},
    "rejected": {"proposed", "excluded"},
    "exported": set(),
}


class FeedbackStateError(ValueError):
    pass


class FeedbackRepository:
    def __init__(self, database: Path) -> None:
        self.store = SQLiteStore(database)
        self._migrate()

    def _migrate(self) -> None:
        with self.store.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reviews(
                  review_id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  case_id TEXT NOT NULL,
                  snapshot_id TEXT NOT NULL,
                  reviewer TEXT NOT NULL,
                  status TEXT NOT NULL,
                  training_state TEXT NOT NULL,
                  context_json TEXT NOT NULL,
                  original_json TEXT NOT NULL,
                  original_sha256 TEXT NOT NULL,
                  corrected_json TEXT,
                  corrected_sha256 TEXT,
                  verification_json TEXT,
                  diff_text TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(run_id, case_id, reviewer)
                );
                CREATE TABLE IF NOT EXISTS feedback_events(
                  event_id TEXT PRIMARY KEY,
                  review_id TEXT NOT NULL REFERENCES reviews(review_id),
                  event_type TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  from_state TEXT,
                  to_state TEXT,
                  details_json TEXT NOT NULL,
                  occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS feedback_events_review_idx
                  ON feedback_events(review_id, occurred_at);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(reviews)").fetchall()
            }
            if "context_json" not in columns:
                connection.execute(
                    "ALTER TABLE reviews ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'"
                )

    def create_review(
        self,
        *,
        run_id: str,
        case_id: str,
        snapshot_id: str,
        reviewer: str,
        run_context: dict[str, Any],
        original_response: dict[str, Any],
    ) -> dict[str, Any]:
        if not all(value.strip() for value in (run_id, case_id, snapshot_id, reviewer)):
            raise ValueError("review identity fields must be non-empty")
        self._validate_context(run_context, snapshot_id)
        review_id = str(uuid.uuid4())
        now = utc_timestamp()
        encoded = canonical_json(original_response)
        with self.store.transaction() as connection:
            connection.execute(
                """INSERT INTO reviews(
                   review_id, run_id, case_id, snapshot_id, reviewer, status, training_state,
                   context_json, original_json, original_sha256, corrected_json,
                   corrected_sha256, verification_json, diff_text, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 'draft', 'excluded', ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)""",
                (
                    review_id, run_id, case_id, snapshot_id, reviewer,
                    canonical_json(run_context), encoded, sha256_json(original_response), now, now,
                ),
            )
            self._event(connection, review_id, "review_created", reviewer, None, "draft", {})
        return self.get(review_id)

    def save_correction(
        self,
        review_id: str,
        *,
        actor: str,
        corrected_response: dict[str, Any],
        verifier: ResearchResponseVerifier,
    ) -> dict[str, Any]:
        report = verifier.verify(corrected_response)
        with self.store.transaction() as connection:
            current = self._row(connection, review_id)
            if current["status"] not in {"draft", "submitted"}:
                raise FeedbackStateError("accepted or rejected reviews cannot be edited")
            original = json.loads(current["original_json"])
            diff = "\n".join(
                difflib.unified_diff(
                    json.dumps(original, ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
                    json.dumps(corrected_response, ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
                    fromfile="original", tofile="corrected", lineterm="",
                )
            )
            connection.execute(
                """UPDATE reviews SET corrected_json=?, corrected_sha256=?, verification_json=?,
                   diff_text=?, updated_at=? WHERE review_id=?""",
                (
                    canonical_json(corrected_response), sha256_json(corrected_response),
                    canonical_json(report.as_dict()), diff, utc_timestamp(), review_id,
                ),
            )
            self._event(
                connection, review_id, "correction_saved", actor, current["status"],
                current["status"], {"deterministic_pass": report.deterministic_pass},
            )
        return self.get(review_id)

    def transition_review(self, review_id: str, *, to_state: str, actor: str) -> dict[str, Any]:
        with self.store.transaction() as connection:
            current = self._row(connection, review_id)
            from_state = current["status"]
            if to_state not in REVIEW_TRANSITIONS.get(from_state, set()):
                raise FeedbackStateError(f"invalid review transition: {from_state} -> {to_state}")
            if to_state in {"submitted", "accepted"}:
                if current["corrected_json"] is None or current["verification_json"] is None:
                    raise FeedbackStateError("a correction must be saved before submission")
                if not json.loads(current["verification_json"])["deterministic_pass"]:
                    raise FeedbackStateError("correction does not pass deterministic verification")
            connection.execute(
                "UPDATE reviews SET status=?, updated_at=? WHERE review_id=?",
                (to_state, utc_timestamp(), review_id),
            )
            self._event(connection, review_id, "review_transition", actor, from_state, to_state, {})
        return self.get(review_id)

    def transition_training(self, review_id: str, *, to_state: str, actor: str) -> dict[str, Any]:
        with self.store.transaction() as connection:
            current = self._row(connection, review_id)
            from_state = current["training_state"]
            if to_state not in TRAINING_TRANSITIONS.get(from_state, set()):
                raise FeedbackStateError(f"invalid training transition: {from_state} -> {to_state}")
            if current["status"] != "accepted":
                raise FeedbackStateError("only accepted feedback can become a training candidate")
            connection.execute(
                "UPDATE reviews SET training_state=?, updated_at=? WHERE review_id=?",
                (to_state, utc_timestamp(), review_id),
            )
            self._event(connection, review_id, "training_transition", actor, from_state, to_state, {})
        return self.get(review_id)

    def get(self, review_id: str) -> dict[str, Any]:
        with self.store.connect() as connection:
            row = self._row(connection, review_id)
            result = dict(row)
            for field in ("context_json", "original_json", "corrected_json", "verification_json"):
                encoded = result.pop(field)
                result[field.removesuffix("_json")] = json.loads(encoded) if encoded else None
            events = connection.execute(
                "SELECT * FROM feedback_events WHERE review_id=? ORDER BY occurred_at, event_id",
                (review_id,),
            ).fetchall()
            result["events"] = [
                {**dict(event), "details": json.loads(event["details_json"])} for event in events
            ]
            for event in result["events"]:
                event.pop("details_json")
            return result

    def list_training_candidates(self, *, state: str = "approved") -> list[dict[str, Any]]:
        if state not in TRAINING_TRANSITIONS:
            raise ValueError("unknown training candidate state")
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT review_id FROM reviews WHERE training_state=? ORDER BY created_at, review_id", (state,)
            ).fetchall()
        return [self.get(row["review_id"]) for row in rows]

    def list_reviews(self) -> list[dict[str, Any]]:
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT review_id FROM reviews ORDER BY updated_at DESC, review_id"
            ).fetchall()
        return [self.get(row["review_id"]) for row in rows]

    @staticmethod
    def _validate_context(context: dict[str, Any], snapshot_id: str) -> None:
        required = {
            "query", "strategy_id", "model", "prompt", "retrieval_config", "snapshot_id",
            "retrieved_context", "estimated_tokens", "cost",
        }
        if not isinstance(context, dict) or set(context) != required:
            raise ValueError("run_context must contain exactly the canonical fields")
        if context["snapshot_id"] != snapshot_id:
            raise ValueError("run_context snapshot does not match the review")
        if any(not isinstance(context[name], str) or not context[name].strip() for name in ("query", "strategy_id", "model", "prompt")):
            raise ValueError("query, strategy, model and prompt must be non-empty")
        if not isinstance(context["retrieval_config"], dict):
            raise ValueError("retrieval_config must be an object")
        if not isinstance(context["retrieved_context"], list):
            raise ValueError("retrieved_context must be an ordered list")
        tokens = context["estimated_tokens"]
        if tokens is not None and (not isinstance(tokens, int) or tokens < 0):
            raise ValueError("estimated_tokens must be null or a non-negative integer")
        cost = context["cost"]
        cost_fields = {"amount", "currency", "source", "verification_status"}
        if not isinstance(cost, dict) or set(cost) != cost_fields:
            raise ValueError("cost must contain amount, currency, source and verification_status")
        if cost["amount"] is None:
            if cost["verification_status"] != "unknown":
                raise ValueError("unknown price must have verification_status=unknown")
        elif not isinstance(cost["amount"], str):
            raise ValueError("cost amount must be a decimal string or null")

    @staticmethod
    def _row(connection, review_id: str):
        row = connection.execute("SELECT * FROM reviews WHERE review_id=?", (review_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown review: {review_id}")
        return row

    @staticmethod
    def _event(connection, review_id, event_type, actor, from_state, to_state, details):
        if not actor.strip():
            raise ValueError("event actor must be non-empty")
        connection.execute(
            "INSERT INTO feedback_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), review_id, event_type, actor, from_state, to_state,
                canonical_json(details), utc_timestamp(),
            ),
        )
