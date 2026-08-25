import type { JobRecord, Overview, ProductWorkspace, ReviewRecord } from "./contracts";

const observedAt = "2026-08-25T09:30:00Z";

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
  experiments: [],
  reviews: [],
  datasets: [],
  training: [],
  exports: [],
};

export const previewReviews: ReviewRecord[] = [];
export const previewJobs: JobRecord[] = [];

export function isPreviewMode(): boolean {
  const location = globalThis.location;
  const localPreview = location?.hostname === "127.0.0.1" || location?.hostname === "localhost";
  return localPreview && new URLSearchParams(location.search).get("preview") === "1";
}
