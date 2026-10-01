"""Reproducciones de auditoría. Solo datos sintéticos en una carpeta nueva.

Ejecutar desde la raíz: python -X utf8 "docs/Auditoria 20260929/reproducir_hallazgos.py"
No contacta servicios externos ni utiliza GPU, vaults o bases de datos del usuario.
"""
from pathlib import Path
import json
import runpy
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.worker.runtime import WorkerRuntime
from local_ai_lab.broker.client import BrokerTaskClient, BrokerHttpResponse

fixtures = runpy.run_path(str(ROOT / "tests/test_distributed_core.py"))
dataset_fixtures = runpy.run_path(str(ROOT / "tests/test_dataset_factory.py"))
runroot = Path(tempfile.mkdtemp(prefix="audit-", dir=Path(__file__).parent))
results = {}

def service(name):
    return CoordinatorService(runroot / name / "state.db")

# Una consulta de control anterior a la cancelación se reutiliza indefinidamente.
s = service("cancel")
_, transport = fixtures["registered"](s, "worker")
job = JobSpec(kind="audit.cancel", payload={})
s.submit_job(job, "submit")
observed = []
def executor(payload, progress):
    s.request_cancel(job_id=job.job_id, idempotency_key="user-cancel")
    progress({"stage": "after_cancel"})
    observed.append("executor_continued_after_cancel")
    return {}
w = WorkerRuntime(node_id="worker", journal_path=runroot / "cancel/journal.db",
                  transport=transport, executors={job.kind: executor},
                  secret_protector=fixtures["TestProtector"]())
try:
    outcome = w.run_once("claim")
except Exception as exc:
    outcome = type(exc).__name__ + ": " + str(exc)
results["cancel_after_start"] = {"observed": observed, "outcome": outcome,
                                "coordinator_state": s.repository.job(job.job_id)["state"]}

# El replay de complete reejecuta efectos fuera de la barrera idempotente.
s = service("complete")
token, transport = fixtures["registered"](s, "worker")
job = JobSpec(kind="strategy.suite.v1", payload={})
s.submit_job(job, "submit")
s.record_product_item(record_id=job.job_id, category="experiment", title="Synthetic",
                      status="EXPERIMENT_QUEUED", artifact_sha256="a" * 64, summary={})
lease = transport.claim(idempotency_key="claim")
transport.ack(lease, idempotency_key="ack")
candidate = {"case_id": "audit-case", "query": "Synthetic question", "snapshot_id": "audit-snapshot",
             "prompt": "Synthetic prompt", "retrieval_config": {}, "retrieved_context": [],
             "original_response": {}, "cost": {"amount": None, "currency": "USD", "source": "not_available", "verification_status": "unknown"}}
payload = {"strategy_id": "B1", "case_ids": ["audit-case"], "review_candidates": [candidate]}
kwargs = dict(node_id="worker", token=token, job_id=job.job_id, attempt_id=lease["attempt_id"],
              lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
              outcome="succeeded", payload=payload, idempotency_key="complete")
s.complete_job(**kwargs)
before = len(s.reviews())
try:
    replay = s.complete_job(**kwargs)
except Exception as exc:
    replay = type(exc).__name__ + ": " + str(exc)
results["completion_replay"] = {"replay_result": replay, "reviews_before": before, "reviews_after": len(s.reviews()),
                                 "status_without_artifact": s.repository.product_record(job.job_id)["status"]}

# Un nodo sin jobs puede descargar un artefacto privado cuyo hash conoce.
s = service("cas")
token, _ = fixtures["registered"](s, "unassigned-worker")
source = runroot / "cas/private-synthetic.txt"
source.write_text("synthetic restricted payload", encoding="utf-8")
artifact = s.artifacts.ingest_file(source)
path = s.artifact_download(node_id="unassigned-worker", token=token, sha256=artifact["sha256"])
results["artifact_authorization"] = {"jobs_for_node": 0, "downloaded": path.read_text(encoding="utf-8")}

# El selector acepta registros en cola sin ninguna medida y sin calidad.
s = service("selection")
for strategy in ("B0", "B1"):
    s.record_product_item(record_id=strategy, category="experiment", title=strategy,
                          status="EXPERIMENT_QUEUED", artifact_sha256="b" * 64,
                          summary={"strategy_id": strategy, "suite_fingerprint": "s" * 64,
                                   "snapshot_hash": "h" * 64, "case_ids": ["c1"], "privacy": "local_only"})
decision = s.select_strategy(experiment_ids=["B0", "B1"], privacy="local_only", max_latency_ms=1,
                             max_cost=None, minimum_cases=1, require_formal_verdict=False)
results["selection_without_measurements"] = {"status": decision["status"], "summary": decision["summary"]}

# La ruta F1 acepta un registro de training, pero no transporta el adaptador.
s = service("f1")
fixtures["registered"](s, "worker")
s.record_product_item(record_id="check", category="experiment", title="Synthetic check",
                      status="CAPABILITIES_SATISFIED", artifact_sha256="c" * 64,
                      summary={"phase": "retrieval", "endpoint": "http://127.0.0.1:8765"})
s.record_product_item(record_id="trained", category="training", title="Synthetic trained model",
                      status="TRAINING_SUCCEEDED", artifact_sha256="d" * 64,
                      summary={"base_model": "trained-base", "adapter_sha256": "e" * 64})
record = s.create_strategy_suite_job(strategy_id="F1", broker_check_id="check",
             broker_endpoint="http://127.0.0.1:9999", node_id="worker",
             target_model={"provider": "local", "deployment": "arbitrary", "model": "unrelated-base"},
             embedding_model=None, embedding_model_fingerprint=None, device="cpu",
             training_job_id="trained", k=5, idempotency_key="f1")
spec = json.loads(s.repository.job(record["record_id"])["spec_json"])
results["f1_adapter_and_endpoint"] = {"accepted": True, "payload_keys": sorted(spec["payload"]),
        "input_mounts": [a["mount_as"] for a in spec["payload"]["input_artifacts"]],
        "model": spec["payload"]["target_model"], "endpoint": spec["payload"]["broker_endpoint"]}

# Un benchmark del registro no interviene en la lista de exclusión del dataset.
s = service("contamination")
from local_ai_lab.knowledge_index.snapshot import SnapshotVerifier
real_snapshot = next((runroot / "f1/experiments").rglob("chunks.jsonl")).parent
manifest = SnapshotVerifier().verify(real_snapshot)["manifest"]
s.record_product_item(record_id=manifest["snapshot_id"], category="snapshot", title="Synthetic complete snapshot",
                      status="COMPLETE", artifact_sha256=manifest["global_hash"], summary={})
s.repository.record_artifact_location(record_id=manifest["snapshot_id"], artifact_kind="vault_snapshot",
                                      local_path=real_snapshot, artifact_sha256=manifest["global_hash"])
definition = runpy.run_path(str(ROOT / "tests/test_real_benchmark.py"))["_definition"]()
definition["snapshot_hash"] = manifest["global_hash"]
definition["cases"][0]["reference_answer"]["evidence"][0]["source_reference"] = "snapshot:sha256:" + manifest["global_hash"] + "#chunk:" + "b" * 64
benchmark = s.register_real_benchmark(definition=definition)
results["benchmark_nonexistent_citations"] = {"status": benchmark["status"], "referenced_note": "note-1", "referenced_chunk": "b" * 64}
approved = dataset_fixtures["_approved"](s.feedback, run="real-benchmark-run", case="project-evolution", reviewer="audit")
dataset = s.build_approved_feedback_dataset(name="audit", split_seed="audit-seed", actor="audit")
results["registered_benchmark_contamination"] = {"included": dataset["summary"]["included"],
        "state": s.feedback.get(approved["review_id"])["training_state"],
        "registry_benchmark_in_exclusions": benchmark["artifact_sha256"] in dataset["summary"]["benchmark_fingerprints"]}

# Un Broker simulado omite identidad de modelo: el cliente acepta el resultado.
class MissingModel:
    def request(self, method, url, **kwargs):
        if url.endswith("capabilities"):
            payload = {}
        elif method == "POST":
            payload = {"task_id": "synthetic-task"}
        elif url.endswith("invocations"):
            payload = {"items": []}
        else:
            payload = {"status": "succeeded", "assistant_content": "Synthetic result"}
        return BrokerHttpResponse(200, json.dumps(payload).encode())
client = BrokerTaskClient(endpoint="http://127.0.0.1:8765", token=None, transport=MissingModel(), poll_interval=0)
invocation = client.invoke(prompt="Synthetic", target_model={"provider": "local", "deployment": "test", "model": "required"},
                           generation={}, json_schema=None, correlation_id="audit")
results["missing_served_model"] = {"accepted": True, "model_used": invocation.model_used,
                                   "telemetry_items": len(invocation.telemetry)}

# El texto principal no se comprueba si findings está vacío.
from local_ai_lab.evaluation.response_verifier import ResearchResponseVerifier
snapshot = next((runroot / "f1/experiments").rglob("chunks.jsonl")).parent
verifier = ResearchResponseVerifier(snapshot)
response = {"answer": "La deuda asciende a 987654321 EUR y pertenece a Inventado Apellido.",
            "findings": [], "contradictions": [], "uncertainties": [], "missing_information": []}
results["unsupported_answer"] = verifier.verify(response).as_dict()
try:
    verifier.verify({**response, "findings": None})
    invalid = "accepted"
except Exception as exc:
    invalid = type(exc).__name__ + ": " + str(exc)
results["invalid_response_shape"] = {"result": invalid}

# Una concesión ya vencida se sigue aceptando si nadie invoca expire_leases.
s = service("expired")
token, transport = fixtures["registered"](s, "worker")
job = JobSpec(kind="audit.expiry", payload={})
s.submit_job(job, "submit")
lease = transport.claim(idempotency_key="claim")
transport.ack(lease, idempotency_key="ack")
with s.repository.transaction() as db:
    db.execute("UPDATE jobs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE job_id=?", (job.job_id,))
result = s.complete_job(node_id="worker", token=token, job_id=job.job_id, attempt_id=lease["attempt_id"],
              lease_token=lease["lease_token"], lease_generation=lease["lease_generation"],
              outcome="succeeded", payload={}, idempotency_key="complete")
results["expired_lease_accepted"] = result

# El mismo worker no puede aceptar un intento nuevo del mismo job reencolado.
from local_ai_lab.worker.journal import WorkerJournal
from datetime import datetime, UTC, timedelta
s = service("reassign")
token, transport = fixtures["registered"](s, "worker")
job = JobSpec(kind="audit.reassign", payload={})
s.submit_job(job, "submit")
first = transport.claim(idempotency_key="claim-1")
journal = WorkerJournal(runroot / "reassign/journal.db", fixtures["TestProtector"]())
journal.accept_lease(first)
s.repository.expire_leases(datetime.now(UTC) + timedelta(hours=1))
s.repository.reconcile_orphan(job.job_id, "requeue")
second = transport.claim(idempotency_key="claim-2")
try:
    journal.accept_lease(second)
    result = "accepted"
except Exception as exc:
    result = type(exc).__name__ + ": " + str(exc)
results["same_worker_reassignment"] = {"new_generation": second["lease_generation"], "result": result}

output = Path(__file__).parent / "resultados_reproducciones.json"
output.write_text(json.dumps({"temporary_directory": str(runroot), "findings": results}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
