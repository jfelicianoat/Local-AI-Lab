/* Formateo y lectura de registros: nada aqui pinta, solo traduce. */

import { Boxes, Cpu, FileSearch, Network, PackageCheck, type LucideIcon } from "lucide-react";

import type { EvidenceStatus, JobRecord, ProductRecord } from "./contracts";
export function summaryRows(summary: Record<string, unknown>): [string, string][] {
  return Object.entries(summary).slice(0, 6).map(([key, value]) => [key, typeof value === "object" ? JSON.stringify(value) : String(value)]);
}
export const terminalJobStates = new Set(["succeeded", "failed", "cancelled"]);

export function relatedRecord(job: JobRecord, records: ProductRecord[]): ProductRecord | undefined {
  return records.find((record) => record.record_id === job.job_id || record.summary.job_id === job.job_id);
}

export function configurationName(record: ProductRecord): string {
  if (typeof record.summary.configuration_label === "string" && record.summary.configuration_label.trim()) {
    return record.summary.configuration_label;
  }
  const strategy = typeof record.summary.strategy_id === "string" ? record.summary.strategy_id : record.title;
  const embedding = typeof record.summary.embedding_model === "string" && record.summary.embedding_model.trim()
    ? record.summary.embedding_model
    : strategy === "R1" ? "lexical" : "embedding no registrado";
  const k = typeof record.summary.k === "number" ? ` · k=${record.summary.k}` : "";
  return `${strategy} · ${embedding}${k}`;
}

export function caseCount(record: ProductRecord): number {
  if (typeof record.summary.case_count === "number") return record.summary.case_count;
  return Array.isArray(record.summary.case_ids) ? record.summary.case_ids.length : 0;
}

export function shortFingerprint(value: unknown): string {
  return typeof value === "string" && value ? `config:${value.slice(0, 12)}…` : "configuración sin fingerprint";
}

export function jobIcon(kind: string): LucideIcon {
  if (kind.includes("training")) return Cpu;
  if (kind.includes("retrieval") || kind.includes("strategy")) return FileSearch;
  if (kind.includes("export")) return PackageCheck;
  if (kind.includes("agent") || kind.includes("broker")) return Network;
  return Boxes;
}

export function friendlyJobKind(kind: string): string {
  const known: Record<string, string> = {
    "retrieval.benchmark.v1": "Benchmark de retrieval",
    "strategy.suite.v1": "Comparación de estrategia",
    "broker.agent_experiment.v1": "Experimento con AI Broker",
    "training.preflight.v1": "Prueba corta de entrenamiento",
    "training.lora.v1": "Entrenamiento LoRA",
    "training.distillation.v1": "Destilación profesor → alumno",
    "model.export.v1": "Exportación de modelo",
  };
  return known[kind] ?? humanize(kind);
}

export function friendlyJobState(state: string): string {
  const known: Record<string, string> = {
    ready: "En cola", leased: "Asignado", acknowledged: "Iniciando",
    running: "En ejecución", succeeded: "Completado", failed: "Fallido",
    cancelled: "Cancelado", cancel_requested: "Cancelando",
  };
  return known[state.toLowerCase()] ?? humanize(state);
}

export function friendlyStage(stage: unknown): string {
  if (typeof stage !== "string" || !stage) return "Sin progreso recibido";
  const known: Record<string, string> = {
    load_local_embedding_model: "Cargando embeddings locales",
    evaluate_ground_truth: "Evaluando ground truth",
    strategy_case: "Ejecutando casos de estrategia",
    teacher_generation: "Generando respuestas del profesor",
    student_training: "Entrenando el alumno",
    save_adapter: "Guardando adapter",
  };
  return known[stage] ?? humanize(stage);
}

export function progressSummary(progress: Record<string, unknown>): string {
  const stage = friendlyStage(progress.stage);
  const current = typeof progress.case === "number" ? progress.case : typeof progress.current === "number" ? progress.current : null;
  const total = typeof progress.total === "number" ? progress.total : null;
  return current !== null && total !== null ? `${stage} · ${current}/${total}` : stage;
}

export function elapsedTime(start: string, end: string): string {
  const startMs = new Date(start).valueOf();
  const endMs = new Date(end).valueOf();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return "No disponible";
  const seconds = Math.round((endMs - startMs) / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${seconds % 60} s`;
}

export function formatDuration(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value < 1000 ? `${value.toFixed(0)} ms` : `${(value / 1000).toFixed(2)} s`;
}

export function humanize(value: string) { return value.replaceAll("_", " "); }
export function formatMetric(value: unknown) { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "—"; }
export function recordStatus(value: string): EvidenceStatus { const folded = value.toLowerCase(); return folded.includes("block") || folded.includes("reject") || folded.includes("incomplete") ? "blocked" : folded.includes("complete") || folded.includes("approved") || folded.includes("verified") ? "tested" : folded.includes("pending") || folded.includes("draft") ? "pending" : "detected"; }
