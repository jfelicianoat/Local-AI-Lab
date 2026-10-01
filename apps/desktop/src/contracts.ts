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
  capability_warning?: string | null;
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

export interface StorageStatus {
  quota_bytes: number;
  committed_bytes: number;
  pending_reserved_bytes: number;
  temporary_chunk_bytes: number;
  available_quota_bytes: number;
  free_disk_bytes: number;
  cleanup_pending_bytes: number;
}

export interface StorageCleanupPlan {
  plan_id: string;
  older_than_days: number;
  cutoff: string;
  created_at: string;
  status?: "applying";
  reclaimable_bytes: number;
  remaining_count: number;
  entries: { kind: "upload" | "blob"; id: string; sha256: string; bytes: number;
    last_activity: string; source_job_id: string | null }[];
}

export interface StorageCleanupResult {
  plan_id: string;
  status: "applied";
  removed_count: number;
  skipped_count: number;
  completed_at: string;
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
  pagination?: Partial<Record<WorkspaceGroup, WorkspacePageMeta>>;
}

export type WorkspaceGroup = "knowledge" | "benchmarks" | "experiments" | "reviews" | "datasets" | "training" | "exports";
export interface WorkspaceCursor { updated_at: string; record_id: string; }
export interface WorkspacePageMeta { total: number; has_more: boolean; cursor: WorkspaceCursor | null; }

export interface HistoryCursor { updated_at: string; id: string; }
export interface HistoryPageMeta { total: number; has_more: boolean; cursor: HistoryCursor | null; }
export interface HistoryPage<T> { items: T[]; pagination: HistoryPageMeta; }

export interface ReviewRecord {
  review_id: string;
  revision: number;
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

export interface TrainingCheckpoint {
  checkpoint_id: string;
  job_id: string;
  node_id: string;
  step: number;
  artifact_sha256: string;
  created_at: string;
  resumed_job_id: string | null;
}

export type MissionStrategy = "prompting" | "lora" | "rag" | "distillation" | "recommend";
export type MissionStageState = "not_started" | "configured" | "executed" | "validated" | "attention";

export interface MissionLink {
  stage_index: number;
  reference_kind: "product" | "job" | "review";
  reference_id: string;
  linked_at: string;
  category: string;
  title: string;
  status: string;
  stage_state: MissionStageState;
  reason?: string;
}

export interface MissionRecord {
  mission_id: string;
  strategy: MissionStrategy;
  task: string;
  success: string;
  constraints: string;
  teacher_source: "broker" | "local" | null;
  teacher_model: string | null;
  student_model: string | null;
  created_at: string;
  updated_at: string;
  links: MissionLink[];
  stage_states: MissionStageState[];
  resume_step: number;
}
