"""Mission plans: a visited screen never counts as completed evidence."""
from __future__ import annotations

import json
from typing import Any

from local_ai_lab.coordinator.service.base import ServicioBase


STAGES: dict[str, tuple[set[str], ...]] = {
    "prompting": (set(), {"benchmark"}, {"experiment"}, {"review"}, {"experiment", "comparison"}),
    "rag": (set(), {"snapshot", "index"}, {"benchmark"}, {"experiment"}, {"review"}, {"experiment", "comparison"}),
    "lora": (set(), {"dataset"}, {"training"}, {"training"}, {"experiment", "comparison"}, {"export"}),
    "distillation": (set(), set(), {"dataset"}, {"training"}, {"training"}, {"experiment", "comparison"}, {"export"}),
    "recommend": (set(), {"benchmark"}, {"experiment"}, {"review"}, {"experiment", "comparison"}),
}
VALIDATED_STATUSES = {
    "COMPLETE", "READY", "HUMAN_APPROVED", "READY_FOR_TRAINING",
    "PREFLIGHT_PASSED", "MODEL_DRIFT_VERIFIED", "EXPORT_SUCCEEDED",
    "RECOMMENDATION",
}
EXECUTED_STATUSES = {"EXPERIMENT_SUCCEEDED", "TRAINING_SUCCEEDED", "DISTILLATION_SUCCEEDED"}
FAILED_STATUSES = {"EXPERIMENT_FAILED", "TRAINING_FAILED", "DISTILLATION_FAILED", "EXPORT_FAILED",
                   "FAILED", "CANCELLED", "NEEDS_REVIEW", "SUPERSEDED"}
RANK = {"not_started": 0, "configured": 1, "executed": 2, "validated": 3}
STAGE_GOALS = {
    "prompting": ("configured", "validated", "executed", "validated", "validated"),
    "rag": ("configured", "validated", "validated", "executed", "validated", "validated"),
    "lora": ("configured", "validated", "validated", "executed", "validated", "validated"),
    "distillation": ("configured", "configured", "validated", "validated", "executed", "validated", "validated"),
    "recommend": ("configured", "validated", "executed", "validated", "validated"),
}


class MisionesMixin(ServicioBase):
    def save_mission(self, *, mission_id: str, strategy: str, task: str,
                     success: str, constraints: str = "", teacher_source: str | None = None,
                     teacher_model: str | None = None,
                     student_model: str | None = None) -> dict[str, Any]:
        if strategy not in STAGES:
            raise ValueError("unknown mission strategy")
        if not mission_id or len(mission_id) > 128:
            raise ValueError("mission ID is required")
        if not task.strip() or not success.strip():
            raise ValueError("mission task and measurable success criterion are required")
        if strategy == "distillation" and teacher_source not in {"local", "broker"}:
            raise ValueError("distillation requires a known teacher source")
        existing = self.repository.mission_plan(mission_id)
        if existing and existing["strategy"] != strategy and existing["links"]:
            raise ValueError("remove linked evidence before changing mission strategy")
        self.repository.save_mission(
            mission_id=mission_id, strategy=strategy, task=task.strip(),
            success=success.strip(), constraints=constraints.strip(),
            teacher_source=teacher_source if strategy == "distillation" else None,
            teacher_model=teacher_model.strip() if strategy == "distillation" and teacher_model else None,
            student_model=student_model.strip() if strategy == "distillation" and student_model else None,
        )
        return self.mission(mission_id)

    def missions(self) -> list[dict[str, Any]]:
        return [self.mission(mission_id) for mission_id in self.repository.mission_ids()]

    def mission(self, mission_id: str) -> dict[str, Any]:
        plan = self.repository.mission_plan(mission_id)
        if plan is None:
            raise KeyError("unknown mission")
        stages = ["not_started"] * len(STAGES[plan["strategy"]])
        if plan["task"] and plan["success"]:
            stages[0] = "configured"
        if plan["strategy"] == "distillation" and plan["teacher_model"] and plan["student_model"]:
            stages[1] = "configured"
        links = self._resolved_mission_links(plan)
        for link in links:
            state = link["stage_state"]
            stage_index = link["stage_index"]
            if state == "attention" and stages[stage_index] == "not_started":
                stages[stage_index] = "attention"
            elif RANK.get(state, 0) > RANK.get(stages[stage_index], 0):
                stages[stage_index] = state
        for stage_index, expected in enumerate(STAGES[plan["strategy"]]):
            if "comparison" in expected and stages[stage_index] in {"executed", "validated"}:
                if not any(link["stage_index"] == stage_index and link["category"] == "comparison"
                           and link["stage_state"] == "validated" for link in links):
                    stages[stage_index] = "configured"
        if plan["strategy"] == "rag" and stages[1] == "validated":
            snapshots = [self.repository.product_record(link["reference_id"]) for link in links
                         if link["stage_index"] == 1 and link["reference_kind"] == "product"
                         and link["category"] == "snapshot" and link["stage_state"] == "validated"]
            indexes = [self.repository.product_record(link["reference_id"]) for link in links
                       if link["stage_index"] == 1 and link["reference_kind"] == "product"
                       and link["category"] == "index" and link["stage_state"] == "validated"]
            if not any(index["summary"].get("snapshot_id") == snapshot["record_id"]
                       and index["summary"].get("snapshot_hash") == snapshot["artifact_sha256"]
                       for snapshot in snapshots for index in indexes):
                stages[1] = "configured"
        resume = next((index for index, state in enumerate(stages)
                       if RANK.get(state, 0) < RANK[STAGE_GOALS[plan["strategy"]][index]]),
                      len(stages) - 1)
        return {**plan, "links": [{key: value for key, value in link.items()
                                  if key not in {"lineage_conflict", "job_kind"}} for link in links],
                "stage_states": stages, "resume_step": resume}

    def link_mission_evidence(self, *, mission_id: str, stage_index: int,
                              reference_kind: str, reference_id: str) -> dict[str, Any]:
        plan = self.repository.mission_plan(mission_id)
        if plan is None:
            raise KeyError("unknown mission")
        stages = STAGES[plan["strategy"]]
        if stage_index < 0 or stage_index >= len(stages) or not stages[stage_index]:
            raise ValueError("this mission stage has no attachable evidence")
        if reference_kind not in {"product", "job", "review"}:
            raise ValueError("unknown mission evidence kind")
        evidence = self._mission_evidence(reference_kind, reference_id)
        if evidence is None:
            raise ValueError("mission evidence does not exist")
        expected = stages[stage_index]
        if evidence["category"] not in expected:
            raise ValueError("evidence does not belong to this mission stage")
        if evidence["category"] == "training" and not self._training_evidence_matches(
            plan["strategy"], stage_index, evidence, reference_kind
        ):
            raise ValueError("training evidence does not match the mission stage")
        proposed = {"stage_index": stage_index, "reference_kind": reference_kind,
                    "reference_id": reference_id}
        resolved = self._resolved_mission_links({**plan, "links": [*plan["links"], proposed]})
        candidate = resolved[-1]
        if candidate.get("lineage_conflict"):
            raise ValueError(candidate["reason"])
        self.repository.add_mission_link(mission_id, stage_index, reference_kind, reference_id)
        return self.mission(mission_id)

    def _resolved_mission_links(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        resources: list[dict[str, Any]] = []
        for link in plan["links"]:
            evidence = self._mission_evidence(link["reference_kind"], link["reference_id"])
            if evidence is None:
                evidence = {"category": "unknown", "title": "Evidencia no disponible",
                            "status": "missing", "stage_state": "attention",
                            "reason": "El resultado vinculado ya no está disponible."}
            links.append({**link, **evidence})
            resources.append(self._mission_resource(link))
        # Dependencies are evaluated again after a prerequisite loses its verified
        # state. A comparison cannot remain validated through an unrelated run.
        for _ in range(len(links) + 1):
            changed = False
            for index, link in enumerate(links):
                if link["status"] == "missing":
                    continue
                reason, conflict = self._mission_lineage(plan, index, links, resources)
                if reason:
                    state = "attention" if conflict or link["stage_state"] == "attention" else "configured"
                    if link["stage_state"] != state:
                        link["stage_state"] = state
                        changed = True
                    link.update(reason=reason, lineage_conflict=conflict)
            if not changed:
                break
        return links

    def _mission_resource(self, link: dict[str, Any]) -> dict[str, Any]:
        kind, reference_id = link["reference_kind"], link["reference_id"]
        if kind == "review":
            try:
                return self.feedback.get(reference_id)
            except KeyError:
                return {}
        record = self.repository.product_record(reference_id)
        if record is not None:
            return {**record["summary"], "record_id": reference_id,
                    "artifact_sha256": record["artifact_sha256"]}
        job = self.repository.job(reference_id) if kind == "job" else None
        if job is None:
            return {}
        spec = json.loads(job["spec_json"])
        return {**spec["payload"], "record_id": reference_id, "kind": spec["kind"]}

    def _mission_lineage(self, plan: dict[str, Any], index: int,
                         links: list[dict[str, Any]], resources: list[dict[str, Any]]) -> tuple[str | None, bool]:
        link, item = links[index], resources[index]
        category, strategy = link["category"], plan["strategy"]

        def require(category_name: str, matches: Any, label: str,
                    choose: Any = lambda _link, _item: True) -> tuple[str | None, bool]:
            anchors = [(other, resource) for offset, (other, resource) in enumerate(zip(links, resources))
                       if offset != index and other["category"] == category_name and choose(other, resource)]
            if not anchors:
                return f"Vincula {label} a esta misión para comprobar la procedencia.", False
            matching = [other for other, resource in anchors if matches(other, resource)]
            if not matching:
                return f"La procedencia de este resultado no coincide con {label} de esta misión.", True
            if not any(other["stage_state"] in {"executed", "validated"} for other in matching):
                return f"Completa o valida {label} vinculado antes de usar este resultado.", False
            return None, False

        if category == "benchmark" and strategy == "rag":
            return require("snapshot", lambda other, resource:
                           item.get("snapshot_hash") == resource.get("artifact_sha256"), "el snapshot")
        if category == "index":
            return require("snapshot", lambda other, resource:
                           item.get("snapshot_id") == other["reference_id"]
                           and item.get("snapshot_hash") == resource.get("artifact_sha256"), "el snapshot")
        if category == "experiment":
            if strategy in {"lora", "distillation"}:
                return require("training", lambda other, resource:
                               item.get("training_job_id") == other["reference_id"]
                               or item.get("record_id") == resource.get("baseline_experiment_id"),
                               "el entrenamiento", lambda other, resource:
                               not str(other["status"]).startswith("PREFLIGHT_"))
            if not item.get("benchmark_id") and not item.get("suite_fingerprint"):
                return "El resultado no conserva la identidad del benchmark utilizado.", False
            issue = require("benchmark", lambda other, resource:
                            (item.get("benchmark_id") == other["reference_id"]
                             and item.get("suite_fingerprint") == resource.get("artifact_sha256"))
                            or (not item.get("benchmark_id")
                                and item.get("suite_fingerprint") == resource.get("artifact_sha256")),
                            "el benchmark")
            if issue[0] or strategy != "rag":
                return issue
            issue = require("snapshot", lambda other, resource:
                            item.get("snapshot_hash") == resource.get("artifact_sha256"), "el snapshot")
            if issue[0] or not item.get("index_id"):
                return issue
            return require("index", lambda other, resource:
                           item["index_id"] == other["reference_id"], "el índice")
        if category == "review":
            return require("experiment", lambda other, resource:
                           item.get("run_id") == other["reference_id"]
                           and (not resource.get("case_ids") or item.get("case_id") in resource["case_ids"]),
                           "el experimento revisado")
        if category == "training":
            model = item.get("student_model", item.get("base_model"))
            if strategy == "distillation" and model and model != plan["student_model"]:
                return "El modelo alumno de este resultado no coincide con el plan.", True
            if strategy == "distillation" and item.get("teacher_model") and (
                item["teacher_model"] != plan["teacher_model"]
                or item.get("teacher_source") != plan["teacher_source"]
            ):
                return "El profesor de este entrenamiento no coincide con el plan.", True
            if not item.get("dataset_id") and not item.get("dataset_fingerprint"):
                return "El resultado no conserva la identidad del dataset utilizado.", False
            issue = require("dataset", lambda other, resource:
                            (item.get("dataset_id") == other["reference_id"]
                             and (not item.get("dataset_fingerprint")
                                  or item["dataset_fingerprint"] == resource.get("artifact_sha256")))
                            or (not item.get("dataset_id")
                                and item.get("dataset_fingerprint") == resource.get("artifact_sha256")), "el dataset")
            if issue[0] or str(link["status"]).startswith("PREFLIGHT_") or item.get("kind") == "training.preflight.v1":
                return issue
            return require("training", lambda other, resource:
                           item.get("preflight_job_id") == other["reference_id"], "el preflight",
                           lambda other, resource: str(other["status"]).startswith("PREFLIGHT_")
                           or resource.get("kind") == "training.preflight.v1")
        if category == "comparison":
            identities = item.get("experiment_ids") or [item.get(key) for key in (
                "baseline_experiment_id", "candidate_experiment_id", "r3_experiment_id", "r4_experiment_id")]
            identities = {identity for identity in identities if isinstance(identity, str) and identity}
            if not identities:
                return "La comparación no conserva las identidades de sus experimentos.", False
            for identity in identities:
                issue = require("experiment", lambda other, resource:
                                other["reference_id"] == identity, "los experimentos comparados")
                if issue[0]:
                    # Missing members can be linked after the comparison itself.
                    return (f"Vincula y completa todos los experimentos de esta comparación en la misión.", False)
            return None, False
        if category == "export":
            return require("training", lambda other, resource:
                           item.get("training_job_id") == other["reference_id"], "el entrenamiento exportado",
                           lambda other, resource: not str(other["status"]).startswith("PREFLIGHT_"))
        return None, False

    def unlink_mission_evidence(self, *, mission_id: str, stage_index: int,
                                reference_kind: str, reference_id: str) -> dict[str, Any]:
        if self.repository.mission_plan(mission_id) is None:
            raise KeyError("unknown mission")
        self.repository.remove_mission_link(mission_id, stage_index, reference_kind, reference_id)
        return self.mission(mission_id)

    def _mission_evidence(self, kind: str, reference_id: str) -> dict[str, Any] | None:
        if kind == "product":
            record = self.repository.product_record(reference_id)
            if record is None:
                return None
            status = record["status"]
            state = ("validated" if status in VALIDATED_STATUSES else
                     "executed" if status in EXECUTED_STATUSES else
                     "attention" if status in FAILED_STATUSES else "configured")
            return {"category": record["category"], "title": record["title"],
                    "status": status, "stage_state": state, "job_kind": record["summary"].get("kind")}
        if kind == "review":
            try:
                review = self.feedback.get(reference_id)
            except KeyError:
                return None
            status = review["status"]
            state = "validated" if status == "accepted" else "attention" if status == "rejected" else "configured"
            return {"category": "review", "title": review["context"].get("query", reference_id),
                    "status": status, "stage_state": state}
        if kind == "job":
            job = self.repository.job(reference_id)
            if job is None:
                return None
            job_kind = json.loads(job["spec_json"])["kind"]
            category = ("training" if job_kind.startswith("training.") else
                        "experiment" if job_kind.startswith(("strategy.", "experiment.")) else
                        "export" if job_kind.startswith(("export.", "model.export.")) else "job")
            status = str(job["state"])
            state = "executed" if status == "succeeded" else "attention" if status in {"failed", "cancelled", "needs_review"} else "configured"
            product = self._mission_evidence("product", reference_id)
            if product is not None:
                state = product["stage_state"]
            return {"category": category, "title": job_kind,
                    "status": status, "stage_state": state}
        return None

    @staticmethod
    def _training_evidence_matches(strategy: str, stage: int,
                                   evidence: dict[str, Any], kind: str) -> bool:
        expected = {
            ("lora", 2): ("PREFLIGHT_", "training.preflight.v1"),
            ("lora", 3): ("TRAINING_", "training.lora.v1"),
            ("distillation", 3): ("PREFLIGHT_", "training.preflight.v1"),
            ("distillation", 4): ("DISTILLATION_", "training.distillation.v1"),
        }.get((strategy, stage))
        if expected is None:
            return True
        return (evidence["title"] == expected[1] if kind == "job" else
                evidence.get("job_kind") == expected[1] or evidence["status"].startswith(expected[0]))
