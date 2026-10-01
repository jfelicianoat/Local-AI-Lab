/* Actividad: ejecuciones en curso y metricas de lo terminado. */
import { useEffect, useMemo, useState } from "react";
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

import type { JobRecord, NodeSummary, ProductWorkspace, TrainingCheckpoint } from "./contracts";
import { cancelJob, loadTrainingCheckpoints, loadTrainingRestart, restartTrainingJob, resumeTrainingCheckpoint } from "./api";
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

export function ActivityBoard({ mode, jobs, nodes, workspace, jobCounts, totalJobs, onRecovered }: { mode: "runs" | "metrics"; jobs: JobRecord[]; nodes: NodeSummary[]; workspace: ProductWorkspace | null; jobCounts: Record<string, number>; totalJobs: number; onRecovered?: () => void }) {
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
  const activeJobs = Object.entries(jobCounts).reduce((sum, [state, count]) =>
    sum + (terminalJobStates.has(state.toLowerCase()) ? 0 : count), 0);
  const completedJobs = Object.entries(jobCounts).reduce((sum, [state, count]) =>
    sum + (state.toLowerCase() === "succeeded" ? count : 0), 0);
  const failedJobs = Object.entries(jobCounts).reduce((sum, [state, count]) =>
    sum + (["failed", "cancelled"].includes(state.toLowerCase()) ? count : 0), 0);

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
    <div className="activity-toolbar"><label><span>Buscar por trabajo, correlación, nodo o estado</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="p. ej. R4, worker-amd o correlation ID" /></label><span>{filteredJobs.length} de {jobs.length} cargadas ({totalJobs} en total)</span></div>
    {jobs.length ? <div className="activity-layout"><div className="run-list" role="list" aria-label="Ejecuciones observadas">{filteredJobs.map((job) => { const JobIcon = jobIcon(job.kind); return <button type="button" role="listitem" key={job.job_id} className={job.job_id === selected?.job_id ? "selected" : ""} onClick={() => setSelectedId(job.job_id)}><JobIcon aria-hidden="true" size={20} /><span><strong>{friendlyJobKind(job.kind)}</strong><small>{job.assigned_node_id ?? "Esperando Worker"} · {formatTime(job.updated_at)}</small></span><b className={`stamp ${recordStatus(job.state)}`}>{friendlyJobState(job.state)}</b></button>; })}</div>{selected ? <article className="run-detail"><header><div><p className="context">Ejecución seleccionada</p><h3 id="runs-heading">{related?.title ?? friendlyJobKind(selected.kind)}</h3></div><span className={`stamp ${recordStatus(selected.state)}`}>{friendlyJobState(selected.state)}</span></header><dl className="run-facts"><div><dt>Worker</dt><dd>{selected.assigned_node_id ?? "Sin asignar"}</dd></div><div><dt>Duración observada</dt><dd>{elapsedTime(selected.created_at, selected.updated_at)}</dd></div><div><dt>Configuración</dt><dd>{related ? configurationName(related) : "No aplica"}</dd></div><div><dt>Última etapa</dt><dd>{friendlyStage(progress?.stage)}</dd></div></dl><ol className="run-timeline"><TimelineStep icon={ListChecks} label="Trabajo creado" detail={formatTime(selected.created_at)} state="complete" /><TimelineStep icon={Cpu} label="Worker asignado" detail={selected.assigned_node_id ?? "Pendiente"} state={selected.assigned_node_id ? "complete" : "pending"} /><TimelineStep icon={Activity} label="Ejecución" detail={progress ? progressSummary(progress) : "Sin progreso recibido"} state={finished ? "complete" : progress ? "active" : "pending"} /><TimelineStep icon={PackageCheck} label="Resultado y artefactos" detail={finished ? friendlyJobState(selected.state) : "Pendiente"} state={finished ? selected.state.toLowerCase() === "succeeded" ? "complete" : "blocked" : "pending"} /></ol><CheckpointRecovery job={selected} nodes={nodes} onRecovered={onRecovered} /><div className="correlation-box"><div><span>Seguimiento de extremo a extremo</span><code>{selected.correlation_id}</code></div><button type="button" onClick={() => void navigator.clipboard?.writeText(selected.correlation_id)}>Copiar ID</button></div></article> : null}</div> : <ActivityEmpty icon={ScrollText} title="Todavía no hay ejecuciones" text="Cuando se envíe un benchmark, entrenamiento o exportación aparecerá aquí con su correlación y recorrido completo." />}
  </section>;
}

function CheckpointRecovery({ job, nodes, onRecovered }: { job: JobRecord; nodes: NodeSummary[]; onRecovered?: () => void }) {
  const [checkpoints, setCheckpoints] = useState<TrainingCheckpoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newJobId, setNewJobId] = useState<string | null>(null);
  const [restartJobId, setRestartJobId] = useState<string | null>(null);
  const [targetNodeId, setTargetNodeId] = useState("");
  useEffect(() => {
    let active = true;
    setCheckpoints([]); setError(null); setNewJobId(null); setRestartJobId(null);
    setTargetNodeId("");
    if (["training.lora.v1", "training.distillation.v1"].includes(job.kind)) {
      void loadTrainingCheckpoints(job.job_id).then((items) => {
        if (active) {
          setCheckpoints(items);
          setTargetNodeId((current) => current || (
            nodes.some((node) => node.node_id === items[0]?.node_id && node.status === "online")
              ? items[0].node_id : nodes.find((node) => node.status === "online")?.node_id ?? ""
          ));
        }
      }).catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "No se pudieron leer los checkpoints.");
      });
      void loadTrainingRestart(job.job_id).then((id) => {
        if (active) setRestartJobId(id);
      }).catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "No se pudo leer el reinicio.");
      });
    }
    return () => { active = false; };
  }, [job.job_id, job.kind]);
  if (!["training.lora.v1", "training.distillation.v1"].includes(job.kind)) return null;
  const recoverable = ["failed", "needs_review"].includes(job.state);
  const recoveryStarted = Boolean(restartJobId || checkpoints.some((item) => item.resumed_job_id));
  if (!recoverable && checkpoints.length === 0 && !error) return null;
  const recover = async (checkpoint: TrainingCheckpoint) => {
    if (busy || recoveryStarted || !targetNodeId || !window.confirm(
      `Se creará un entrenamiento nuevo desde el paso ${checkpoint.step}. El intento anterior conservará su historial. ¿Reanudar?`,
    )) return;
    setBusy(true); setError(null);
    try {
      const resumedId = await resumeTrainingCheckpoint(job.job_id, checkpoint.checkpoint_id, targetNodeId);
      setNewJobId(resumedId);
      setCheckpoints((items) => items.map((item) => item.checkpoint_id === checkpoint.checkpoint_id
        ? { ...item, resumed_job_id: resumedId } : item));
      onRecovered?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo reanudar el entrenamiento.");
    } finally { setBusy(false); }
  };
  const restart = async () => {
    if (busy || recoveryStarted || !targetNodeId) return;
    const detail = job.kind === "training.distillation.v1"
      ? "Se volverán a generar las respuestas del profesor; si usa Broker, podría tener un coste."
      : "El entrenamiento volverá a empezar desde el paso 0.";
    if (!window.confirm(`${detail} Se creará un trabajo nuevo y se conservará el historial. ¿Reiniciar?`)) return;
    setBusy(true); setError(null);
    try {
      const id = await restartTrainingJob(job.job_id, targetNodeId);
      setRestartJobId(id); setNewJobId(id); onRecovered?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo reiniciar el entrenamiento.");
    } finally { setBusy(false); }
  };
  const discard = async () => {
    if (busy || !window.confirm("El trabajo quedará cancelado y se conservará su historial. ¿Descartar?")) return;
    setBusy(true); setError(null);
    try { await cancelJob(job.job_id); onRecovered?.(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo cancelar el trabajo."); }
    finally { setBusy(false); }
  };
  return <section className="checkpoint-recovery" aria-label="Recuperación del entrenamiento">
    <h4>Recuperación del entrenamiento</h4>
    {recoverable && !recoveryStarted ? <label>
      Worker de destino
      <select value={targetNodeId} onChange={(event) => setTargetNodeId(event.target.value)}>
        <option value="">Selecciona un Worker en línea</option>
        {nodes.filter((node) => node.status === "online").map((node) =>
          <option key={node.node_id} value={node.node_id}>{node.hostname} ({node.node_id})</option>)}
      </select>
    </label> : null}
    {recoverable && !nodes.some((node) => node.status === "online") ? <p>No hay un Worker en línea para continuar.</p> : null}
    {checkpoints.length ? checkpoints.map((checkpoint) => <div className="checkpoint-row" key={checkpoint.checkpoint_id}>
      <span>Paso {checkpoint.step} · {formatTime(checkpoint.created_at)}</span>
      {checkpoint.resumed_job_id ? <small>Reanudado en {checkpoint.resumed_job_id}</small>
        : recoverable && !recoveryStarted ? <button type="button" disabled={busy || !targetNodeId} onClick={() => void recover(checkpoint)}>
          {busy ? "Preparando…" : `Reanudar desde paso ${checkpoint.step}`}</button>
          : <small>{recoveryStarted ? "Ya existe una recuperación"
            : job.state === "cancelled" ? "Trabajo descartado" : "Disponible si se interrumpe"}</small>}
    </div>) : <p>No hay un checkpoint publicado para este intento.</p>}
    {recoverable && !recoveryStarted ? <div className="checkpoint-actions">
      <button type="button" disabled={busy || !targetNodeId} onClick={() => void restart()}>
        {busy ? "Preparando…" : "Reiniciar desde cero"}
      </button>
      {job.state === "needs_review" ? <button type="button" disabled={busy} onClick={() => void discard()}>
        Descartar trabajo
      </button> : null}
    </div> : null}
    {restartJobId ? <p role="status">Reiniciado en {restartJobId}</p> : null}
    {newJobId && !restartJobId ? <p role="status">Nuevo entrenamiento creado: {newJobId}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}

export function TimelineStep({ icon: Icon, label, detail, state }: { icon: LucideIcon; label: string; detail: string; state: "complete" | "active" | "pending" | "blocked" }) {
  return <li className={state}><Icon aria-hidden="true" size={18} /><div><strong>{label}</strong><span>{detail}</span></div></li>;
}

export function ActivityEmpty({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return <div className="activity-empty"><Icon aria-hidden="true" size={28} /><div><strong>{title}</strong><p>{text}</p></div></div>;
}
