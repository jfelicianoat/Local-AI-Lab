export type EvidenceStatus = "tested" | "detected" | "pending" | "blocked";

export interface EvidenceItem {
  id: string;
  label: string;
  status: EvidenceStatus;
  artifact_sha256: string | null;
  source_reference: string | null;
  observed_at: string | null;
}

export interface NodeSummary {
  node_id: string;
  hostname: string;
  status: string;
  last_heartbeat_at: string;
  capabilities_observed: boolean;
  tested_workloads: string[];
}

export interface Overview {
  schema_version: "local-ai-lab.overview.v1";
  observed_at: string;
  phase: string;
  gate_status: string;
  nodes: NodeSummary[];
  job_counts: Record<string, number>;
  evidence: EvidenceItem[];
  external_dependencies: {
    ai_broker: string;
    vault: string;
    model_drift: string;
  };
}

export interface ProductRecord {
  record_id: string;
  category: "snapshot" | "index" | "benchmark" | "experiment" | "comparison" | "review" | "dataset" | "training" | "export";
  title: string;
  status: string;
  artifact_sha256: string;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProductWorkspace {
  schema_version: "local-ai-lab.workspace.v1";
  observed_at: string;
  knowledge: ProductRecord[];
  benchmarks: ProductRecord[];
  experiments: ProductRecord[];
  reviews: ProductRecord[];
  datasets: ProductRecord[];
  training: ProductRecord[];
  exports: ProductRecord[];
}

export interface ReviewRecord {
  review_id: string;
  run_id: string;
  case_id: string;
  snapshot_id: string;
  reviewer: string;
  status: "draft" | "submitted" | "accepted" | "rejected";
  training_state: "excluded" | "proposed" | "approved" | "rejected" | "exported";
  context: Record<string, unknown>;
  original: Record<string, unknown>;
  corrected: Record<string, unknown> | null;
  verification: { deterministic_pass?: boolean; errors?: string[] } | null;
  diff_text: string | null;
  updated_at: string;
}

export interface JobRecord {
  job_id: string;
  kind: string;
  state: string;
  correlation_id: string;
  assigned_node_id: string | null;
  lease_generation: number;
  control_action: string | null;
  latest_progress: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}
