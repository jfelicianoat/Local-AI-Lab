/* Actividad: ejecuciones en curso y metricas de lo terminado. */
import { useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  Cpu,
  Gauge,
  ListChecks,
  Network,
  PackageCheck,
  ScrollText,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import type { JobRecord, ProductWorkspace } from "./contracts";
import {
  caseCount,
  configurationName,
  elapsedTime,
  formatDuration,
  formatMetric,
  friendlyJobKind,
  friendlyJobState,
  friendlyStage,
  jobIcon,
  progressSummary,
  recordStatus,
  relatedRecord,
  shortFingerprint,
  terminalJobStates,
} from "./format";
import { formatTime } from "./states";

export function ActivityBoard({ mode, jobs, workspace }: { mode: "runs" | "metrics"; jobs: JobRecord[]; workspace: ProductWorkspace | null }) {
  const records = useMemo(() => workspace ? [
    ...workspace.knowledge, ...workspace.benchmarks, ...workspace.experiments,
    ...workspace.reviews, ...workspace.datasets, ...workspace.training, ...workspace.exports,
  ] : [], [workspace]);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(jobs[0]?.job_id ?? "");
  const selected = jobs.find((job) => job.job_id === selectedId) ?? jobs[0];
  const filteredJobs = jobs.filter((job) => {
    const related = relatedRecord(job, records);
    return [job.job_id, job.correlation_id, job.kind, job.state, job.assigned_node_id, related?.title]
      .some((value) => String(value ?? "").toLocaleLowerCase("es").includes(query.toLocaleLowerCase("es")));
  });
  const metricRecords = records.filter((record) =>
    ["experiment", "comparison"].includes(record.category) && (
      typeof record.summary.recall_at_k === "number"
      || typeof record.summary.ndcg_at_k === "number"
      || typeof record.summary.latency_ms === "number"
      || record.summary.formal_status === "model_drift_verified"
    )
  );
  const activeJobs = jobs.filter((job) => !terminalJobStates.has(job.state.toLowerCase())).length;
  const completedJobs = jobs.filter((job) => job.state.toLowerCase() === "succeeded").length;
  const failedJobs = jobs.filter((job) => ["failed", "cancelled"].includes(job.state.toLowerCase())).length;

  if (mode === "metrics") return <section className="activity-board" aria-labelledby="metrics-heading">
    <div className="activity-summary"><article><BarChart3 aria-hidden="true" /><div><strong>{metricRecords.length}</strong><span>configuraciones medidas</span></div></article><article><BookOpenCheck aria-hidden="true" /><div><strong>{metricRecords.filter((record) => record.summary.formal_status === "model_drift_verified").length}</strong><span>con informe formal</span></div></article><article><Gauge aria-hidden="true" /><div><strong>{metricRecords.filter((record) => caseCount(record) >= 20).length}</strong><span>con 20+ casos</span></div></article></div>
    <div className="experiment-caveat"><Network aria-hidden="true" size={20} /><div><strong>La unidad de comparación es la configuración completa</strong><p>Embedding, modelo, k, suite y snapshot forman parte del resultado. R4 no se presenta como mejora establecida; con menos de 20 casos se señala evidencia insuficiente para generalizar.</p></div></div>
    {metricRecords.length ? <div className="table-wrap metric-ledger"><table><caption id="metrics-heading">Resultados observados por configuración</caption><thead><tr><th>Configuración</th><th>Retrieval</th><th>Latencia</th><th>Muestra</th><th>Verificación</th><th>Ámbito de la conclusión</th></tr></thead><tbody>{metricRecords.map((record) => { const cases = caseCount(record); return <tr key={record.record_id}><td><strong>{configurationName(record)}</strong><small>{shortFingerprint(record.summary.configuration_fingerprint ?? record.artifact_sha256)}</small></td><td><span>Recall {formatMetric(record.summary.recall_at_k)}</span><small>nDCG {formatMetric(record.summary.ndcg_at_k)} · MRR {formatMetric(record.summary.mrr)}</small></td><td>{formatDuration(record.summary.latency_ms)}</td><td><strong>{cases || "—"}</strong><small>{cases > 0 && cases < 20 ? "Potencia insuficiente" : cases >= 20 ? "Umbral mínimo cubierto" : "No registrado"}</small></td><td><span className={`stamp ${record.summary.formal_status === "model_drift_verified" ? "tested" : "pending"}`}>{String(record.summary.formal_status ?? "unverified")}</span></td><td>{record.summary.claim_scope === "configuration_specific" ? "Solo esta configuración" : "No generalizable sin comparación formal"}</td></tr>; })}</tbody></table></div> : <ActivityEmpty icon={BarChart3} title="Todavía no hay métricas comparables" text="Ejecuta estrategias sobre la misma suite y snapshot. La vista conservará el embedding y el resto de la configuración." />}
  </section>;

  const related = selected ? relatedRecord(selected, records) : undefined;
  const progress = selected?.latest_progress ?? null;
  const finished = selected ? terminalJobStates.has(selected.state.toLowerCase()) : false;
  return <section className="activity-board" aria-labelledby="runs-heading">
    <div className="activity-summary"><article><Activity aria-hidden="true" /><div><strong>{activeJobs}</strong><span>en curso</span></div></article><article><CheckCircle2 aria-hidden="true" /><div><strong>{completedJobs}</strong><span>completados</span></div></article><article><ShieldCheck aria-hidden="true" /><div><strong>{failedJobs}</strong><span>requieren atención</span></div></article></div>
    <div className="activity-toolbar"><label><span>Buscar por trabajo, correlación, nodo o estado</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="p. ej. R4, worker-amd o correlation ID" /></label><span>{filteredJobs.length} de {jobs.length} ejecuciones</span></div>
    {jobs.length ? <div className="activity-layout"><div className="run-list" role="list" aria-label="Ejecuciones observadas">{filteredJobs.map((job) => { const JobIcon = jobIcon(job.kind); return <button type="button" role="listitem" key={job.job_id} className={job.job_id === selected?.job_id ? "selected" : ""} onClick={() => setSelectedId(job.job_id)}><JobIcon aria-hidden="true" size={20} /><span><strong>{friendlyJobKind(job.kind)}</strong><small>{job.assigned_node_id ?? "Esperando Worker"} · {formatTime(job.updated_at)}</small></span><b className={`stamp ${recordStatus(job.state)}`}>{friendlyJobState(job.state)}</b></button>; })}</div>{selected ? <article className="run-detail"><header><div><p className="context">Ejecución seleccionada</p><h3 id="runs-heading">{related?.title ?? friendlyJobKind(selected.kind)}</h3></div><span className={`stamp ${recordStatus(selected.state)}`}>{friendlyJobState(selected.state)}</span></header><dl className="run-facts"><div><dt>Worker</dt><dd>{selected.assigned_node_id ?? "Sin asignar"}</dd></div><div><dt>Duración observada</dt><dd>{elapsedTime(selected.created_at, selected.updated_at)}</dd></div><div><dt>Configuración</dt><dd>{related ? configurationName(related) : "No aplica"}</dd></div><div><dt>Última etapa</dt><dd>{friendlyStage(progress?.stage)}</dd></div></dl><ol className="run-timeline"><TimelineStep icon={ListChecks} label="Trabajo creado" detail={formatTime(selected.created_at)} state="complete" /><TimelineStep icon={Cpu} label="Worker asignado" detail={selected.assigned_node_id ?? "Pendiente"} state={selected.assigned_node_id ? "complete" : "pending"} /><TimelineStep icon={Activity} label="Ejecución" detail={progress ? progressSummary(progress) : "Sin progreso recibido"} state={finished ? "complete" : progress ? "active" : "pending"} /><TimelineStep icon={PackageCheck} label="Resultado y artefactos" detail={finished ? friendlyJobState(selected.state) : "Pendiente"} state={finished ? selected.state.toLowerCase() === "succeeded" ? "complete" : "blocked" : "pending"} /></ol><div className="correlation-box"><div><span>Seguimiento de extremo a extremo</span><code>{selected.correlation_id}</code></div><button type="button" onClick={() => void navigator.clipboard?.writeText(selected.correlation_id)}>Copiar ID</button></div></article> : null}</div> : <ActivityEmpty icon={ScrollText} title="Todavía no hay ejecuciones" text="Cuando se envíe un benchmark, entrenamiento o exportación aparecerá aquí con su correlación y recorrido completo." />}
  </section>;
}

export function TimelineStep({ icon: Icon, label, detail, state }: { icon: LucideIcon; label: string; detail: string; state: "complete" | "active" | "pending" | "blocked" }) {
  return <li className={state}><Icon aria-hidden="true" size={18} /><div><strong>{label}</strong><span>{detail}</span></div></li>;
}

export function ActivityEmpty({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return <div className="activity-empty"><Icon aria-hidden="true" size={28} /><div><strong>{title}</strong><p>{text}</p></div></div>;
}
