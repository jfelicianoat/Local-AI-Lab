import type { JobRecord, Overview, ProductRecord, ProductWorkspace, ReviewRecord } from "./contracts";

const observedAt = "2026-08-25T09:30:00Z";
const previewExperiments: ProductRecord[] = [
  {
    record_id: "preview-r3-minilm", category: "experiment", title: "R3 · corpus controlado",
    status: "EXPERIMENT_SUCCEEDED", artifact_sha256: "3".repeat(64),
    summary: { job_id: "preview-r3-minilm", strategy_id: "R3", embedding_model: "all-MiniLM-L6-v2", embedding_model_fingerprint: "a".repeat(64), configuration_label: "R3 · all-MiniLM-L6-v2 · k=5", configuration_fingerprint: "c".repeat(64), k: 5, case_ids: ["c1", "c2", "c3", "c4", "c5"], recall_at_k: 0.8, precision_at_k: 0.68, mrr: 0.72, ndcg_at_k: 0.733, latency_ms: 842, formal_status: "model_drift_verified", privacy: "local_only" },
    created_at: "2026-08-25T09:10:00Z", updated_at: "2026-08-25T09:12:08Z",
  },
  {
    record_id: "preview-r4-minilm", category: "experiment", title: "R4 · corpus controlado",
    status: "EXPERIMENT_SUCCEEDED", artifact_sha256: "4".repeat(64),
    summary: { job_id: "preview-r4-minilm", strategy_id: "R4", embedding_model: "all-MiniLM-L6-v2", embedding_model_fingerprint: "a".repeat(64), configuration_label: "R4 · all-MiniLM-L6-v2 · k=5", configuration_fingerprint: "d".repeat(64), k: 5, case_ids: ["c1", "c2", "c3", "c4", "c5"], recall_at_k: 0.8, precision_at_k: 0.64, mrr: 0.69, ndcg_at_k: 0.7, latency_ms: 916, formal_status: "model_drift_verified", privacy: "local_only" },
    created_at: "2026-08-25T09:13:00Z", updated_at: "2026-08-25T09:15:22Z",
  },
];

export const previewOverview: Overview = {
  schema_version: "local-ai-lab.overview.v1",
  observed_at: observedAt,
  phase: "phase1",
  gate_status: "pending_real_nodes",
  nodes: [],
  job_counts: {},
  evidence: [
    { id: "phase1.core", label: "Núcleo distribuido", status: "pending", artifact_sha256: null, source_reference: null, observed_at: null },
    { id: "phase1.nvidia", label: "Worker NVIDIA real", status: "pending", artifact_sha256: null, source_reference: null, observed_at: null },
    { id: "phase1.amd", label: "Worker AMD real", status: "pending", artifact_sha256: null, source_reference: null, observed_at: null },
    { id: "phase1.disconnect", label: "Recuperación real entre PCs", status: "pending", artifact_sha256: null, source_reference: null, observed_at: null },
    { id: "phase1.tls", label: "Conexión segura entre equipos", status: "pending", artifact_sha256: null, source_reference: null, observed_at: null },
  ],
  external_dependencies: { ai_broker: "unknown", vault: "unknown", model_drift: "unknown" },
};

export const previewWorkspace: ProductWorkspace = {
  schema_version: "local-ai-lab.workspace.v1",
  observed_at: observedAt,
  knowledge: [],
  benchmarks: [],
  experiments: previewExperiments,
  reviews: [],
  datasets: [],
  training: [],
  exports: [],
};

export const previewReviews: ReviewRecord[] = [];
export const previewJobs: JobRecord[] = [
  { job_id: "preview-r4-minilm", kind: "retrieval.benchmark.v1", state: "succeeded", correlation_id: "corr-r4-minilm-20260825", assigned_node_id: "worker-nvidia", lease_generation: 1, control_action: null, latest_progress: { stage: "evaluate_ground_truth", case: 5, total: 5 }, created_at: "2026-08-25T09:13:00Z", updated_at: "2026-08-25T09:15:22Z" },
  { job_id: "preview-r3-minilm", kind: "retrieval.benchmark.v1", state: "succeeded", correlation_id: "corr-r3-minilm-20260825", assigned_node_id: "worker-nvidia", lease_generation: 1, control_action: null, latest_progress: { stage: "evaluate_ground_truth", case: 5, total: 5 }, created_at: "2026-08-25T09:10:00Z", updated_at: "2026-08-25T09:12:08Z" },
  { job_id: "preview-distillation", kind: "training.distillation.v1", state: "running", correlation_id: "corr-distillation-qwen-student", assigned_node_id: "worker-amd", lease_generation: 2, control_action: null, latest_progress: { stage: "teacher_generation", current: 32, total: 120 }, created_at: "2026-08-25T09:20:00Z", updated_at: observedAt },
];

export function isPreviewMode(): boolean {
  const location = globalThis.location;
  const localPreview = location?.hostname === "127.0.0.1" || location?.hostname === "localhost";
  return localPreview && new URLSearchParams(location.search).get("preview") === "1";
}
