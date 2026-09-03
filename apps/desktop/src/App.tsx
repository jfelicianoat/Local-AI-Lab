/*
THESIS: Local AI Lab starts from the operator's goal and turns evidence into a guided mission.
OWN-WORLD: Mineral-white ruled surfaces, ink-green type, cobalt selection, semantic evidence stamps.
STORY: The operator chooses an outcome, sees the complete route, and always has one exact next action.
FIRST VIEWPORT: A compact mission rail, a complete training route, and a live plan preview.
FORM: Guided local-research workbench; existing evidence and expert controls remain reachable.
*/
import { useCallback, useEffect, useMemo, useState } from "react";
import { Hexagon, RefreshCw, ShieldCheck } from "lucide-react";
import { loadJobs, loadOverview, loadProductWorkspace, loadReviews } from "./api";
import type { EvidenceStatus, JobRecord, Overview, ProductWorkspace, ReviewRecord } from "./contracts";
import { navigation, pageCopy } from "./navigation";
// La version sale del package.json en tiempo de compilacion: al reportar un
// fallo lo primero que hace falta es saber contra que build se estaba mirando.
const APP_VERSION = __APP_VERSION__;

import { EmptyState, ErrorState, LoadingState, StaleState, formatTime } from "./states";
import { DependencySummary, EvidenceTable, NodeTable, RecordBoard, StatusCount } from "./overview";
import { MissionBoard } from "./mission";
import {
  AgentExperimentPanel,
  BrokerCompatibilityPanel,
  ExperimentBoard,
  StrategyRunnerPanel,
  StrategySelectorPanel,
} from "./experiments";
import { DatasetBoard, DistillationPanel, OperationsBoard } from "./datasets";
import { ActivityBoard } from "./activity";
import { KnowledgeBoard, ReviewBoard } from "./knowledge";
export default function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [product, setProduct] = useState<ProductWorkspace | null>(null);
  const [reviews, setReviews] = useState<ReviewRecord[]>([]);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [active, setActive] = useState("Misiones");
  const [status, setStatus] = useState<"loading" | "ready" | "stale" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const [nextOverview, nextProduct, nextReviews, nextJobs] = await Promise.all([loadOverview(), loadProductWorkspace(), loadReviews(), loadJobs()]);
      setOverview(nextOverview);
      setProduct(nextProduct);
      setReviews(nextReviews);
      setJobs(nextJobs);
      setStatus("ready");
    } catch (reason) {
      setStatus(overview ? "stale" : "error");
      setError(reason instanceof Error ? reason.message : "No se pudo leer el Coordinator.");
    }
  }, [overview]);

  useEffect(() => {
    void refresh();
  }, []); // run once at desktop boot; later refreshes are explicit

  const evidenceCounts = useMemo(() => {
    const counts: Record<EvidenceStatus, number> = { tested: 0, detected: 0, pending: 0, blocked: 0 };
    overview?.evidence.forEach((item) => counts[item.status]++);
    return counts;
  }, [overview]);

  return (
    <div className="app-shell guided-shell">
      <aside className="rail" aria-label="Navegación principal">
        <div className="brand"><span aria-hidden="true"><Hexagon size={28} strokeWidth={2.25} /></span><div><strong>Local AI Lab</strong><small>Entorno local · privado · v{APP_VERSION}</small></div></div>
        <nav>{["Misión actual", "Ejecución", "Observabilidad", "Configuración"].map((group) => <div className="nav-group" key={group}><p>{group}</p>{navigation.filter((item) => item.group === group).map((item) => {
          const Icon = item.icon;
          return (
          <button key={item.label} className={active === item.label ? "active" : ""} onClick={() => setActive(item.label)} aria-current={active === item.label ? "page" : undefined}>
            <Icon aria-hidden="true" size={19} strokeWidth={1.8} />{item.label}
          </button>
        )})}</div>)}</nav>
        <div className="privacy-note"><strong><ShieldCheck aria-hidden="true" size={17} /> Entorno local activo</strong><span>Solo este equipo</span><small>Todo el procesamiento y la evidencia permanecen en el laboratorio.</small></div>
      </aside>

      <main className="workspace">
        <header className="app-topbar">
          <div><small>Espacio de trabajo</small><strong>{overview?.phase.toUpperCase() ?? "LOCAL"}</strong></div>
          <div className="topbar-trust"><strong><ShieldCheck aria-hidden="true" size={17} /> Todo se ejecuta en este equipo</strong><small>Ningún dato sale del entorno local.</small></div>
          <button className="refresh" disabled={status === "loading"} onClick={() => void refresh()}><RefreshCw aria-hidden="true" size={16} />{status === "loading" ? "Actualizando…" : "Actualizar"}</button>
        </header>

        {status === "error" ? <ErrorState message={error ?? "Error desconocido"} retry={() => void refresh()} /> : null}
        {status === "loading" && !overview ? <LoadingState /> : null}
        {status === "stale" ? <StaleState message={error ?? "No se pudo actualizar"} retry={() => void refresh()} /> : null}
        {overview ? (
          <div className={status === "loading" ? "content scanning" : "content"} aria-busy={status === "loading"}>
            {active === "Misiones" ? <MissionBoard overview={overview} product={product} onNavigate={setActive} /> : <>
              <header className="workspace-header"><div><p className="context">{active}</p><h1>{pageCopy[active].title}</h1><p>{pageCopy[active].description}</p></div></header>
              {active === "Evidencia" ? <section className="status-strip" aria-label="Resumen de evidencia">
                <StatusCount status="tested" label="Probado" count={evidenceCounts.tested} />
                <StatusCount status="detected" label="Detectado" count={evidenceCounts.detected} />
                <StatusCount status="pending" label="Pendiente" count={evidenceCounts.pending} />
                <StatusCount status="blocked" label="Bloqueado" count={evidenceCounts.blocked} />
              </section> : null}
              <section className="ledger" aria-labelledby="ledger-title">
              <div className="section-heading"><div><p>Coordinator · {formatTime(overview.observed_at)}</p><h2 id="ledger-title">{pageCopy[active].title}</h2></div><code>{active === "Evidencia" ? overview.schema_version : product?.schema_version ?? "workspace pendiente"}</code></div>
              {active === "Planes y borradores" ? <RecordBoard records={[...(product?.datasets ?? []), ...(product?.training ?? []), ...(product?.exports ?? [])]} emptyTitle="Todavía no hay planes guardados" emptyText="Crea una misión guiada para empezar y poder retomarla después." /> : null}
              {active === "Evidencia" ? <><EvidenceTable items={overview.evidence} /><NodeTable nodes={overview.nodes} /></> : null}
              {active === "Recursos" ? <><KnowledgeBoard records={product?.knowledge ?? []} onCreated={(record) => setProduct((current) => current ? { ...current, knowledge: [record, ...current.knowledge] } : current)} /><NodeTable nodes={overview.nodes} /></> : null}
              {active === "Experimentos" ? <><ExperimentBoard records={[...(product?.benchmarks ?? []), ...(product?.experiments ?? [])]} snapshots={(product?.knowledge ?? []).filter((item) => item.category === "snapshot" && item.status === "COMPLETE")} nodes={overview.nodes} onCreated={(record) => setProduct((current) => current ? record.category === "benchmark" ? { ...current, benchmarks: [record, ...current.benchmarks] } : { ...current, experiments: [record, ...current.experiments] } : current)} /><BrokerCompatibilityPanel onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} /><StrategyRunnerPanel records={product?.experiments ?? []} training={product?.training ?? []} nodes={overview.nodes} onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} /><AgentExperimentPanel records={product?.experiments ?? []} nodes={overview.nodes} onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} /><StrategySelectorPanel records={product?.experiments ?? []} onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} /></> : null}
              {active === "Revisiones" ? <ReviewBoard reviews={reviews} onChanged={(changed) => setReviews((current) => current.map((item) => item.review_id === changed.review_id ? changed : item))} /> : null}
              {active === "Datasets" ? <DatasetBoard records={product?.datasets ?? []} approvedCount={reviews.filter((review) => review.training_state === "approved").length} onCreated={(record) => { setProduct((current) => current ? { ...current, datasets: [record, ...current.datasets] } : current); void refresh(); }} /> : null}
              {active === "Entrenamientos" ? <><OperationsBoard records={[...(product?.training ?? []), ...(product?.exports ?? [])]} datasets={product?.datasets ?? []} experiments={product?.experiments ?? []} nodes={overview.nodes} jobs={jobs} onChanged={() => void refresh()} /><DistillationPanel datasets={product?.datasets ?? []} preflights={(product?.training ?? []).filter((record) => record.status === "PREFLIGHT_PASSED")} experiments={product?.experiments ?? []} onChanged={() => void refresh()} /></> : null}
              {active === "Registros" || active === "Métricas" ? <ActivityBoard mode={active === "Registros" ? "runs" : "metrics"} jobs={jobs} workspace={product} /> : null}
              {active === "Configuración" ? <><BrokerCompatibilityPanel onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} /><DependencySummary overview={overview} /></> : null}
            </section>
            </>}
          </div>
        ) : status === "ready" ? <EmptyState /> : null}
      </main>
    </div>
  );
}
