import { invoke } from "@tauri-apps/api/core";
import type { JobRecord, Overview, ProductRecord, ProductWorkspace, ReviewRecord } from "./contracts";
import { isPreviewMode, previewJobs, previewOverview, previewReviews, previewWorkspace } from "./previewData";

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

export async function loadReviews(): Promise<ReviewRecord[]> {
  if (isPreviewMode()) return previewReviews;
  const payload: unknown = await invoke("load_reviews");
  if (!Array.isArray(payload) || !payload.every(isReview)) {
    throw new Error("El Coordinator devolvió revisiones no reconocidas.");
  }
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

export async function cancelJob(jobId: string): Promise<{ job_id: string; state: string }> {
  const payload: unknown = await invoke("cancel_job", { jobId });
  if (!payload || typeof payload !== "object" || typeof (payload as { job_id?: unknown }).job_id !== "string" || typeof (payload as { state?: unknown }).state !== "string") {
    throw new Error("No se pudo validar la cancelación del job.");
  }
  return payload as { job_id: string; state: string };
}

export async function saveReviewCorrection(reviewId: string, correctedResponse: Record<string, unknown>): Promise<ReviewRecord> {
  const payload: unknown = await invoke("save_review_correction", { reviewId, correctedResponse });
  if (!isReview(payload)) throw new Error("No se pudo validar la revisión guardada.");
  return payload;
}

export async function changeReviewState(reviewId: string, toState: string): Promise<ReviewRecord> {
  const payload: unknown = await invoke("transition_review", { reviewId, toState });
  if (!isReview(payload)) throw new Error("No se pudo validar el nuevo estado de revisión.");
  return payload;
}

export async function changeTrainingState(reviewId: string, toState: string): Promise<ReviewRecord> {
  const payload: unknown = await invoke("transition_training_candidate", { reviewId, toState });
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

export async function runControlledRetrievalBenchmark(k: number): Promise<ProductRecord> {
  const payload: unknown = await invoke("run_controlled_retrieval_benchmark", { k });
  if (!isRecord(payload)) throw new Error("No se pudo validar el informe del benchmark.");
  return payload;
}

export async function createSemanticRetrievalBenchmark(input: {
  strategyId: "R2" | "R3" | "R4"; nodeId: string; embeddingModel: string;
  embeddingModelFingerprint: string; device: string; k: number;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_semantic_retrieval_benchmark", input);
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
  endpoint: string; phase: "phase0" | "retrieval" | "formal_evaluation" | "agent_experiments";
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
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_broker_agent_experiment", input);
  if (!isRecord(payload)) throw new Error("No se pudo validar el experimento A1/M1.");
  return payload;
}

export async function createStrategyRun(input: {
  strategyId: string; brokerCheckId: string; brokerEndpoint: string; nodeId: string;
  provider: string; deployment: string; model: string; embeddingModel?: string;
  embeddingModelFingerprint?: string; device: string; trainingJobId?: string; k: number;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_strategy_run", {
    ...input,
    embeddingModel: input.embeddingModel?.trim() || null,
    embeddingModelFingerprint: input.embeddingModelFingerprint?.trim() || null,
    trainingJobId: input.trainingJobId?.trim() || null,
  });
  if (!isRecord(payload)) throw new Error("No se pudo validar la ejecución de estrategia.");
  return payload;
}

export async function buildApprovedFeedbackDataset(name: string, splitSeed: string): Promise<ProductRecord> {
  const payload: unknown = await invoke("build_approved_feedback_dataset", { name, splitSeed });
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
  objective: string; hypothesis: string; approvedBy: string; epochs: number;
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
  objective: string; hypothesis: string; approvedBy: string; epochs: number;
  temperature: number; maxNewTokens: number;
}): Promise<ProductRecord> {
  const payload: unknown = await invoke("create_distillation_run", input);
  if (!isRecord(payload)) throw new Error("No se pudo validar el entrenamiento por destilación.");
  return payload;
}

export async function createModelExport(input: {
  trainingJobId: string; nodeId: string; formats: string[]; licenseId: string;
  servingRuntime: string; llamaCppConverter?: string;
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
      Array.isArray(node.tested_workloads) && node.tested_workloads.every((item) => typeof item === "string"),
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
  return candidate.schema_version === "local-ai-lab.workspace.v1" &&
    typeof candidate.observed_at === "string" &&
    groups.every((group) => Array.isArray(group) && group.every(isRecord));
}

function isReview(value: unknown): value is ReviewRecord {
  if (!value || typeof value !== "object") return false;
  const review = value as Partial<ReviewRecord>;
  return typeof review.review_id === "string" && typeof review.run_id === "string" &&
    typeof review.case_id === "string" && typeof review.snapshot_id === "string" &&
    typeof review.reviewer === "string" && typeof review.status === "string" &&
    typeof review.training_state === "string" && !!review.context && !!review.original &&
    typeof review.updated_at === "string";
}

function isJob(value: unknown): value is JobRecord {
  if (!value || typeof value !== "object") return false;
  const job = value as Partial<JobRecord>;
  return typeof job.job_id === "string" && typeof job.kind === "string" &&
    typeof job.state === "string" && typeof job.correlation_id === "string" &&
    typeof job.lease_generation === "number" && typeof job.created_at === "string" &&
    typeof job.updated_at === "string";
}
