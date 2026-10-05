import { invoke } from "@tauri-apps/api/core";
import type { HistoryCursor, HistoryPage, JobRecord, MissionRecord, MissionStrategy, Overview, ProductRecord, ProductWorkspace, ReviewRecord, StorageStatus, StorageCleanupPlan, StorageCleanupResult, TrainingCheckpoint, WorkspaceCursor, WorkspaceGroup } from "./contracts";
import { isPreviewMode, previewJobs, previewOverview, previewReviews, previewWorkspace } from "./previewData";
import { workspaceGroups } from "./workspacePagination";
export { mergeProductWorkspace, workspaceGroups } from "./workspacePagination";
export { mergeHistoryPage } from "./historyPagination";

export async function loadStorage(): Promise<StorageStatus | null> {
  if (isPreviewMode()) return null;
  const payload: unknown = await invoke("load_storage");
  if (!isObject(payload) || ![
    "quota_bytes", "committed_bytes", "pending_reserved_bytes",
    "temporary_chunk_bytes", "available_quota_bytes", "free_disk_bytes", "cleanup_pending_bytes",
  ].every((key) => typeof payload[key] === "number" && Number.isSafeInteger(payload[key]) && payload[key] >= 0)) {
    throw new Error("El Coordinator devolvió un estado de almacenamiento no reconocido.");
  }
  return payload as unknown as StorageStatus;
}

function isCleanupPlan(value: unknown): value is StorageCleanupPlan {
  if (!isObject(value) || typeof value.plan_id !== "string" || typeof value.cutoff !== "string"
    || typeof value.created_at !== "string" || !Array.isArray(value.entries)
    || (value.status !== undefined && value.status !== "applying")) return false;
  return ["older_than_days", "reclaimable_bytes", "remaining_count"].every((key) =>
    typeof value[key] === "number" && Number.isSafeInteger(value[key]) && value[key] >= 0)
    && value.entries.every((item) => isObject(item) && ["upload", "blob"].includes(String(item.kind))
      && typeof item.id === "string" && typeof item.sha256 === "string"
      && typeof item.bytes === "number" && Number.isSafeInteger(item.bytes) && item.bytes >= 0
      && typeof item.last_activity === "string"
      && (item.source_job_id === null || typeof item.source_job_id === "string"));
}

export async function planStorageCleanup(olderThanDays: number): Promise<StorageCleanupPlan> {
  if (isPreviewMode()) throw new Error("La vista previa no puede limpiar archivos.");
  const payload: unknown = await invoke("plan_storage_cleanup", { olderThanDays });
  if (!isCleanupPlan(payload)) throw new Error("No se pudo validar la propuesta de limpieza.");
  return payload;
}

export async function loadPendingStorageCleanup(): Promise<StorageCleanupPlan | null> {
  if (isPreviewMode()) return null;
  const payload: unknown = await invoke("load_pending_storage_cleanup");
  if (payload !== null && !isCleanupPlan(payload)) throw new Error("No se pudo leer la limpieza pendiente.");
  return payload;
}

export async function applyStorageCleanup(planId: string): Promise<StorageCleanupResult> {
  if (isPreviewMode()) throw new Error("La vista previa no puede limpiar archivos.");
  const payload: unknown = await invoke("apply_storage_cleanup", { planId });
  if (!isObject(payload) || payload.plan_id !== planId || payload.status !== "applied"
    || typeof payload.completed_at !== "string" || !["removed_count", "skipped_count"].every((key) =>
      typeof payload[key] === "number" && Number.isSafeInteger(payload[key]) && payload[key] >= 0)) {
    throw new Error("No se pudo confirmar el resultado de la limpieza.");
  }
  return payload as unknown as StorageCleanupResult;
}

export async function loadOverview(): Promise<Overview> {
  if (isPreviewMode()) return previewOverview;
  const payload: unknown = await invoke("load_overview");
  if (!isOverview(payload)) {
    throw new Error("El Coordinator devolvió un contrato de vista no reconocido.");
  }
  return payload;
}

export async function loadProductWorkspace(): Promise<ProductWorkspace> {
  if (isPreviewMode()) return previewWorkspace;
  const payload: unknown = await invoke("load_workspace");
  if (!isProductWorkspace(payload)) {
    throw new Error("El Coordinator devolvió un espacio de trabajo no reconocido.");
  }
  return payload;
}

export async function loadMoreProductWorkspace(
  groups: WorkspaceGroup[], cursors: Partial<Record<WorkspaceGroup, WorkspaceCursor | null>>,
): Promise<ProductWorkspace> {
  if (isPreviewMode()) return previewWorkspace;
  const payload: unknown = await invoke("load_workspace_page", { groups, cursors, limit: 50 });
  if (!isProductWorkspace(payload) || !payload.pagination) {
    throw new Error("No se pudo validar la página del historial.");
  }
  return payload;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isMission(value: unknown): value is MissionRecord {
  return isObject(value) && typeof value.mission_id === "string" &&
    typeof value.strategy === "string" && typeof value.task === "string" &&
    typeof value.success === "string" && Array.isArray(value.links) &&
    Array.isArray(value.stage_states) && typeof value.resume_step === "number";
}

export async function loadMissions(): Promise<MissionRecord[]> {
  if (isPreviewMode()) return [];
  const payload: unknown = await invoke("load_missions");
  if (!Array.isArray(payload) || !payload.every(isMission)) throw new Error("No se pudieron validar las misiones guardadas.");
  if (window.localStorage.getItem("local-ai-lab.missions.imported.v1") === "yes") return payload;
  const raw = window.localStorage.getItem("local-ai-lab.missions.v2");
  const legacy = window.localStorage.getItem("local-ai-lab.mission-draft.v1");
  const drafts: unknown[] = [];
  let priorSelectedId: string | null = null;
  try {
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (isObject(parsed) && Array.isArray(parsed.plans)) {
        drafts.push(...parsed.plans);
        if (typeof parsed.selectedId === "string") priorSelectedId = parsed.selectedId;
      }
    } else if (legacy) {
      const parsed: unknown = JSON.parse(legacy);
      if (isObject(parsed)) { drafts.push({ ...parsed, id: "legacy" }); priorSelectedId = "legacy"; }
    }
  } catch { /* A damaged local draft cannot block the saved Coordinator plans. */ }
  const imported = [...payload];
  for (const item of drafts) {
    if (!isObject(item) || typeof item.id !== "string" || !/^[a-zA-Z0-9-]{1,128}$/.test(item.id) ||
        typeof item.strategy !== "string" || !["prompting", "lora", "rag", "distillation", "recommend"].includes(item.strategy) ||
        typeof item.task !== "string" || !item.task.trim() || typeof item.success !== "string" || !item.success.trim() ||
        imported.some((mission) => mission.mission_id === item.id)) continue;
    imported.push(await saveMission({
      missionId: item.id, strategy: item.strategy as MissionStrategy,
      task: item.task, success: item.success,
      constraints: typeof item.constraints === "string" ? item.constraints : "",
      teacherSource: item.teacherSource === "local" ? "local" :
        item.teacherSource === "broker" || item.strategy === "distillation" ? "broker" : undefined,
      teacherModel: typeof item.teacherModel === "string" ? item.teacherModel : undefined,
      studentModel: typeof item.studentModel === "string" ? item.studentModel : undefined,
    }));
  }
  if (priorSelectedId && !window.localStorage.getItem("local-ai-lab.selected-mission.v1") &&
      imported.some((mission) => mission.mission_id === priorSelectedId)) {
    window.localStorage.setItem("local-ai-lab.selected-mission.v1", priorSelectedId);
  }
  window.localStorage.setItem("local-ai-lab.missions.imported.v1", "yes");
  return imported;
}

export async function saveMission(input: {
  missionId: string; strategy: MissionStrategy; task: string; success: string;
  constraints: string; teacherSource?: "broker" | "local";
  teacherModel?: string; studentModel?: string;
}): Promise<MissionRecord> {
  const payload: unknown = await invoke("save_mission", input);
  if (!isMission(payload)) throw new Error("No se pudo validar la misión guardada.");
  return payload;
}

export async function linkMissionEvidence(input: {
  missionId: string; stageIndex: number; referenceKind: "product" | "job" | "review";
  referenceId: string;
}): Promise<MissionRecord> {
  const payload: unknown = await invoke("link_mission_evidence", input);
  if (!isMission(payload)) throw new Error("No se pudo validar la evidencia vinculada.");
  return payload;
}

export async function unlinkMissionEvidence(input: {
  missionId: string; stageIndex: number; referenceKind: "product" | "job" | "review";
  referenceId: string;
}): Promise<MissionRecord> {
  const payload: unknown = await invoke("unlink_mission_evidence", input);
  if (!isMission(payload)) throw new Error("No se pudo validar la misión actualizada.");
  return payload;
}

export async function loadReviews(): Promise<ReviewRecord[]> {
  if (isPreviewMode()) return previewReviews;
  const payload: unknown = await invoke("load_reviews");
  if (!Array.isArray(payload) || !payload.every(isReview)) {
    throw new Error("El Coordinator devolvió revisiones no reconocidas.");
  }
  return payload;
}

export async function loadReviewsPage(cursor: HistoryCursor | null = null): Promise<HistoryPage<ReviewRecord>> {
  if (isPreviewMode()) return { items: previewReviews, pagination: {
    total: previewReviews.length, has_more: false, cursor: null,
  } };
  const payload: unknown = await invoke("load_reviews_page", { limit: 50, cursor });
  if (!isHistoryPage(payload, isReview)) throw new Error("El Coordinator devolvió una página de revisiones no reconocida.");
  return payload;
}

export interface ManualExampleHit {
  chunk_id: string; note_id: string; note_path: string;
  section: string; content: string; source_reference: string;
}

export async function previewManualExample(snapshotId: string, indexId: string, query: string): Promise<ManualExampleHit[]> {
  const payload: unknown = await invoke("preview_manual_example", { snapshotId, indexId, query });
  if (!Array.isArray(payload) || !payload.every((item) => item && typeof item === "object" && typeof item.chunk_id === "string" && typeof item.content === "string")) {
    throw new Error("El Coordinator devolvió fuentes no reconocidas.");
  }
  return payload as ManualExampleHit[];
}

export async function createManualExample(input: {
  snapshotId: string; indexId: string; query: string; answer: string; chunkIds: string[]; reviewer: string;
}): Promise<ReviewRecord> {
  const payload: unknown = await invoke("create_manual_example", input);
  if (!isReview(payload)) throw new Error("No se pudo validar el ejemplo importado.");
  return payload;
}

export async function loadJobs(): Promise<JobRecord[]> {
  if (isPreviewMode()) return previewJobs;
  const payload: unknown = await invoke("load_jobs");
  if (!Array.isArray(payload) || !payload.every(isJob)) {
    throw new Error("El Coordinator devolvió jobs no reconocidos.");
  }
  return payload;
}

export async function loadJobsPage(cursor: HistoryCursor | null = null): Promise<HistoryPage<JobRecord>> {
  if (isPreviewMode()) return { items: previewJobs, pagination: {
    total: previewJobs.length, has_more: false, cursor: null,
  } };
  const payload: unknown = await invoke("load_jobs_page", { limit: 50, cursor });
  if (!isHistoryPage(payload, isJob)) throw new Error("El Coordinator devolvió una página de jobs no reconocida.");
  return payload;
}

function isHistoryPage<T>(value: unknown, isItem: (item: unknown) => item is T): value is HistoryPage<T> {
  if (!isObject(value) || !Array.isArray(value.items) || !value.items.every(isItem) ||
      !isObject(value.pagination)) return false;
  const meta = value.pagination;
  return typeof meta.total === "number" && Number.isSafeInteger(meta.total) && meta.total >= 0 &&
    typeof meta.has_more === "boolean" && (meta.cursor === null ||
      (isObject(meta.cursor) && typeof meta.cursor.updated_at === "string" &&
        typeof meta.cursor.id === "string"));
}

export async function revokeNode(nodeId: string): Promise<void> {
  const payload: unknown = await invoke("revoke_node", { nodeId });
  if (!payload || typeof payload !== "object" || (payload as { status?: unknown }).status !== "revoked") {
    throw new Error("No se pudo confirmar la revocación del Worker.");
  }
}

export async function saveProductArtifact(recordId: string): Promise<string> {
  if (isPreviewMode()) throw new Error("La vista previa no tiene archivos descargables.");
  const path: unknown = await invoke("save_product_artifact", { recordId });
  if (typeof path !== "string" || !path) throw new Error("No se pudo confirmar dónde se guardó el resultado.");
  return path;
}

export async function cancelJob(jobId: string): Promise<{ job_id: string; state: string }> {
  const payload: unknown = await invoke("cancel_job", { jobId });
  if (!payload || typeof payload !== "object" || typeof (payload as { job_id?: unknown }).job_id !== "string" || typeof (payload as { state?: unknown }).state !== "string") {
    throw new Error("No se pudo validar la cancelación del job.");
  }
  return payload as { job_id: string; state: string };
}

export async function loadTrainingCheckpoints(jobId: string): Promise<TrainingCheckpoint[]> {
  if (isPreviewMode()) return [];
  const payload: unknown = await invoke("load_training_checkpoints", { jobId });
  if (!Array.isArray(payload) || !payload.every((item) => item && typeof item === "object"
    && typeof item.checkpoint_id === "string" && typeof item.job_id === "string"
    && typeof item.step === "number" && typeof item.node_id === "string"
    && typeof item.artifact_sha256 === "string"
    && typeof item.created_at === "string"
    && (item.resumed_job_id === null || typeof item.resumed_job_id === "string"))) {
    throw new Error("El Coordinator devolvió checkpoints no reconocidos.");
  }
  return payload as TrainingCheckpoint[];
}

export async function loadTrainingRestart(jobId: string): Promise<string | null> {
  if (isPreviewMode()) return null;
  const payload: unknown = await invoke("load_training_restart", { jobId });
  if (!payload || typeof payload !== "object") throw new Error("No se pudo leer el reinicio del entrenamiento.");
  const value = (payload as { restarted_job_id?: unknown }).restarted_job_id;
  if (value !== null && typeof value !== "string") throw new Error("El reinicio del entrenamiento no es válido.");
  return value;
}

export async function resumeTrainingCheckpoint(jobId: string, checkpointId: string, nodeId: string): Promise<string> {
  if (isPreviewMode()) throw new Error("La vista previa no puede reanudar entrenamientos.");
  const payload: unknown = await invoke("resume_training_checkpoint", { jobId, checkpointId, nodeId });
  if (!payload || typeof payload !== "object" || typeof (payload as { job_id?: unknown }).job_id !== "string") {
    throw new Error("No se pudo confirmar el nuevo entrenamiento.");
  }
  return (payload as { job_id: string }).job_id;
}

export async function restartTrainingJob(jobId: string, nodeId: string): Promise<string> {
  if (isPreviewMode()) throw new Error("La vista previa no puede reiniciar entrenamientos.");
  const payload: unknown = await invoke("restart_training_job", { jobId, nodeId });
  if (!payload || typeof payload !== "object" || typeof (payload as { job_id?: unknown }).job_id !== "string") {
    throw new Error("No se pudo confirmar el nuevo entrenamiento.");
  }
  return (payload as { job_id: string }).job_id;
}

export class ReviewConflictError extends Error {
  constructor() { super("Esta revisión cambió en otra sesión. Tu corrección local se conserva. Revisa la versión guardada antes de continuar."); }
}

async function mutateReview(command: string, arguments_: Record<string, unknown>): Promise<unknown> {
  try { return await invoke(command, arguments_); }
  catch (error) {
    if (String(error).includes("(409)")) throw new ReviewConflictError();
    throw error;
  }
}

export async function saveReviewCorrection(reviewId: string, correctedResponse: Record<string, unknown>, expectedRevision: number): Promise<ReviewRecord> {
  const payload = await mutateReview("save_review_correction", { reviewId, correctedResponse, expectedRevision });
  if (!isReview(payload)) throw new Error("No se pudo validar la revisión guardada.");
  return payload;
}

export async function changeReviewState(reviewId: string, toState: string, expectedRevision: number, reason?: string): Promise<ReviewRecord> {
  const payload = await mutateReview("transition_review", { reviewId, toState, reason, expectedRevision });
  if (!isReview(payload)) throw new Error("No se pudo validar el nuevo estado de revisión.");
  return payload;
}

export async function changeTrainingState(reviewId: string, toState: string, expectedRevision: number): Promise<ReviewRecord> {
  const payload = await mutateReview("transition_training_candidate", { reviewId, toState, expectedRevision });
  if (!isReview(payload)) throw new Error("No se pudo validar el estado de training.");
  return payload;
}

export async function discoverVaults(allowedRoot: string): Promise<string[]> {
  const payload: unknown = await invoke("discover_vaults", { allowedRoot });
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { vaults?: unknown }).vaults) ||
      !(payload as { vaults: unknown[] }).vaults.every((item) => typeof item === "string")) {
    throw new Error("No se pudo validar la lista de vaults.");
  }
  return (payload as { vaults: string[] }).vaults;
}

export async function createVaultSnapshot(allowedRoot: string, vaultName: string): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_vault_snapshot", { allowedRoot, vaultName });
  if (!isRecord(payload)) throw new Error("No se pudo validar el snapshot creado.");
  return payload;
}

export async function createKnowledgeIndex(snapshotId: string, previousIndexId?: string): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_knowledge_index", {
    snapshotId,
    previousIndexId: previousIndexId ?? null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar el índice creado.");
  return payload;
}

export type SuiteSelection = { benchmarkId?: string; snapshotId?: string; indexId?: string };

export async function runControlledRetrievalBenchmark(k: number, selection: SuiteSelection = {}): Promise<ProductRecord> {
  const payload: unknown = await invoke("run_controlled_retrieval_benchmark", {
    k, benchmarkId: selection.benchmarkId ?? null,
    snapshotId: selection.snapshotId ?? null, indexId: selection.indexId ?? null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar el informe del benchmark.");
  return payload;
}

export async function createSemanticRetrievalBenchmark(input: {
  strategyId: "R2" | "R3" | "R4"; nodeId: string; embeddingModel: string;
  embeddingModelFingerprint: string; device: string; k: number;
} & SuiteSelection): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_semantic_retrieval_benchmark", {
    ...input, benchmarkId: input.benchmarkId ?? null,
    snapshotId: input.snapshotId ?? null, indexId: input.indexId ?? null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar el job de retrieval.");
  return payload;
}

export async function registerRealBenchmark(definition: Record<string, unknown>): Promise<ProductRecord> {
  const payload: unknown = await invoke("register_real_benchmark", { definition });
  if (!isRecord(payload)) throw new Error("No se pudo validar el benchmark real.");
  return payload;
}

export async function runModelDriftComparison(input: {
  r3ExperimentId: string; r4ExperimentId: string; executable: string;
  workingDirectory: string; confirmed: boolean;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("run_model_drift_comparison", input);
  if (!isRecord(payload)) throw new Error("No se pudo validar el informe formal de Model Drift.");
  return payload;
}

export async function checkBrokerCompatibility(input: {
  endpoint: string; phase: "phase0" | "retrieval" | "formal_evaluation" | "agent_experiments" | "demonstrable_execution";
  token?: string;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("check_broker_compatibility", {
    ...input, token: input.token?.trim() || null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar el informe de compatibilidad del Broker.");
  return payload;
}

export async function selectStrategy(input: {
  experimentIds: string[]; privacy?: string; maxLatencyMs?: number;
  maxCost?: string; minimumCases: number; requireFormalVerdict: boolean;
  qualityMetric: "quality.fidelity" | "retrieval.recall_at_k"; minimumQuality: number;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("select_strategy", {
    ...input,
    privacy: input.privacy?.trim() || null,
    maxLatencyMs: input.maxLatencyMs ?? null,
    maxCost: input.maxCost?.trim() || null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar la recomendación de estrategia.");
  return payload;
}

export async function createBrokerAgentExperiment(input: {
  strategyId: "A1" | "M1"; brokerCheckId: string; brokerEndpoint: string;
  nodeId: string; provider: string; deployment: string; model: string;
  embeddingModel: string; embeddingModelFingerprint: string; device: string; k: number;
} & SuiteSelection): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_broker_agent_experiment", {
    ...input, benchmarkId: input.benchmarkId ?? null,
    snapshotId: input.snapshotId ?? null, indexId: input.indexId ?? null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar el experimento A1/M1.");
  return payload;
}

export async function createStrategyRun(input: {
  strategyId: string; brokerCheckId: string; brokerEndpoint: string; nodeId: string;
  provider: string; deployment: string; model: string; embeddingModel?: string;
  embeddingModelFingerprint?: string; device: string; trainingJobId?: string; k: number;
  evaluation?: import("./System1EvaluationPanel").EvaluationPolicy;
} & SuiteSelection): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_strategy_run", {
    ...input,
    evaluation: input.evaluation ?? null,
    embeddingModel: input.embeddingModel?.trim() || null,
    embeddingModelFingerprint: input.embeddingModelFingerprint?.trim() || null,
    trainingJobId: input.trainingJobId?.trim() || null,
    benchmarkId: input.benchmarkId ?? null,
    snapshotId: input.snapshotId ?? null, indexId: input.indexId ?? null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar la ejecución de estrategia.");
  return payload;
}

export async function buildApprovedFeedbackDataset(name: string, splitSeed: string, sourceSnapshotId: string): Promise<ProductRecord> {
  const payload: unknown = await invoke("build_approved_feedback_dataset", { name, splitSeed, sourceSnapshotId });
  if (!isRecord(payload)) throw new Error("No se pudo validar el dataset construido.");
  return payload;
}

export async function createTrainingPreflight(input: {
  datasetId: string; nodeId: string; baseModel: string; dtype: "bf16" | "fp16";
  seed: number; maxLength: number; rank: number;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_training_preflight", input);
  if (!isRecord(payload)) throw new Error("No se pudo validar el preflight creado.");
  return payload;
}

export async function createTrainingRun(input: {
  datasetId: string; preflightJobId: string; baselineExperimentId: string;
  objective: string; hypothesis: string; containsMutableFacts: boolean;
  minimumQualityGain: number; approvedBy: string; epochs: number;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_training_run", input);
  if (!isRecord(payload)) throw new Error("No se pudo validar el entrenamiento creado.");
  return payload;
}

export async function createDistillationRun(input: {
  datasetId: string; preflightJobId: string; baselineExperimentId: string;
  teacherSource: "local" | "broker"; brokerCheckId?: string;
  teacherBrokerEndpoint?: string; teacherProvider?: string; teacherDeployment?: string;
  teacherModel: string; teacherModelFingerprint?: string;
  studentModel: string; studentModelFingerprint: string;
  teacherLicense: string; studentLicense: string;
  teacherOutputsTrainingAllowed: boolean; studentFinetuningAllowed: boolean;
  objective: string; hypothesis: string; containsMutableFacts: boolean;
  minimumQualityGain: number; approvedBy: string; epochs: number;
  temperature: number; maxNewTokens: number;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_distillation_run", input);
  if (!isRecord(payload)) throw new Error("No se pudo validar el entrenamiento por destilación.");
  return payload;
}

export async function createModelExport(input: {
  trainingJobId: string; nodeId: string; formats: string[]; licenseId: string;
  servingRuntime: string; llamaCppConverter?: string;
  verificationOnly?: boolean;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_model_export", {
    ...input,
    llamaCppConverter: input.llamaCppConverter?.trim() || null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar la exportación creada.");
  return payload;
}

function isOverview(value: unknown): value is Overview {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Overview>;
  const validEvidence = candidate.evidence?.every(
    (item) =>
      !!item &&
      typeof item.id === "string" &&
      typeof item.label === "string" &&
      ["tested", "detected", "pending", "blocked"].includes(item.status),
  );
  const validNodes = candidate.nodes?.every(
    (node) =>
      !!node &&
      typeof node.node_id === "string" &&
      typeof node.hostname === "string" &&
      typeof node.status === "string" &&
      typeof node.last_heartbeat_at === "string" &&
      typeof node.capabilities_observed === "boolean" &&
      Array.isArray(node.tested_workloads) && node.tested_workloads.every((item) => typeof item === "string") &&
      (node.capability_warning === undefined || node.capability_warning === null || typeof node.capability_warning === "string"),
  );
  return (
    candidate.schema_version === "local-ai-lab.overview.v1" &&
    typeof candidate.phase === "string" &&
    Array.isArray(candidate.nodes) && validNodes === true &&
    Array.isArray(candidate.evidence) && validEvidence === true &&
    !!candidate.external_dependencies &&
    typeof candidate.external_dependencies.ai_broker === "string" &&
    typeof candidate.external_dependencies.vault === "string" &&
    typeof candidate.external_dependencies.model_drift === "string"
  );
}

function isRecord(value: unknown): value is ProductRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<ProductRecord>;
  return (
    typeof record.record_id === "string" && typeof record.category === "string" &&
    typeof record.title === "string" && typeof record.status === "string" &&
    typeof record.artifact_sha256 === "string" && record.artifact_sha256.length === 64 &&
    !!record.summary && typeof record.summary === "object" &&
    typeof record.created_at === "string" && typeof record.updated_at === "string"
  );
}

function isProductWorkspace(value: unknown): value is ProductWorkspace {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProductWorkspace>;
  const groups = [
    candidate.knowledge, candidate.benchmarks, candidate.experiments, candidate.reviews,
    candidate.datasets, candidate.training, candidate.exports,
  ];
  const validPagination = candidate.pagination === undefined ||
    (isObject(candidate.pagination) && Object.entries(candidate.pagination).every(([group, info]) =>
      workspaceGroups.includes(group as WorkspaceGroup) && isObject(info) &&
      typeof info.total === "number" && typeof info.has_more === "boolean" &&
      (info.cursor === null || (isObject(info.cursor) &&
        typeof info.cursor.updated_at === "string" && typeof info.cursor.record_id === "string"))));
  return candidate.schema_version === "local-ai-lab.workspace.v1" &&
    typeof candidate.observed_at === "string" &&
    validPagination && groups.every((group) => Array.isArray(group) && group.every(isRecord));
}

function isReview(value: unknown): value is ReviewRecord {
  if (!value || typeof value !== "object") return false;
  const review = value as Partial<ReviewRecord>;
  return typeof review.review_id === "string" && typeof review.run_id === "string" &&
    typeof review.case_id === "string" && typeof review.snapshot_id === "string" &&
    typeof review.reviewer === "string" && typeof review.status === "string" &&
    typeof review.training_state === "string" && !!review.context && !!review.original &&
    typeof review.updated_at === "string" && typeof review.revision === "number" &&
    Number.isInteger(review.revision) && review.revision >= 1;
}

function isJob(value: unknown): value is JobRecord {
  if (!value || typeof value !== "object") return false;
  const job = value as Partial<JobRecord>;
  return typeof job.job_id === "string" && typeof job.kind === "string" &&
    typeof job.state === "string" && typeof job.correlation_id === "string" &&
    typeof job.lease_generation === "number" && typeof job.created_at === "string" &&
    typeof job.updated_at === "string";
}
