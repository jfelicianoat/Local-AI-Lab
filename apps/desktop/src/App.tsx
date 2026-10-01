/*
THESIS: Local AI Lab starts from the operator's goal and turns evidence into a guided mission.
OWN-WORLD: Mineral-white ruled surfaces, ink-green type, cobalt selection, semantic evidence stamps.
STORY: The operator chooses an outcome, sees the complete route, and always has one exact next action.
FIRST VIEWPORT: A compact mission rail, a complete training route, and a live plan preview.
FORM: Guided local-research workbench; existing evidence and expert controls remain reachable.
*/
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Hexagon, RefreshCw, ShieldCheck } from "lucide-react";
import { loadJobsPage, loadMissions, loadMoreProductWorkspace, loadOverview, loadProductWorkspace, loadReviewsPage, loadStorage, mergeHistoryPage, mergeProductWorkspace, revokeNode, workspaceGroups } from "./api";
import type { SuiteSelection } from "./api";
import type { EvidenceStatus, HistoryPage, JobRecord, MissionRecord, Overview, ProductWorkspace, ReviewRecord, StorageStatus } from "./contracts";
import { navigation, pageCopy } from "./navigation";
// La version sale del package.json en tiempo de compilacion: al reportar un
// fallo lo primero que hace falta es saber contra que build se estaba mirando.
const APP_VERSION = __APP_VERSION__;

import { EmptyState, ErrorState, LoadingState, StaleState, formatTime } from "./states";
import { DependencySummary, EvidenceTable, NodeTable, RecordBoard, StatusCount } from "./overview";
import { StorageCleanupPanel } from "./StorageCleanupPanel";
import { MissionBoard, MissionList } from "./mission";
import {
  AgentExperimentPanel,
  BrokerCompatibilityPanel,
  ExperimentBoard,
  StrategyRunnerPanel,
  StrategySelectorPanel,
  SuiteContextPanel,
} from "./experiments";
import { DatasetBoard, DistillationPanel, OperationsBoard } from "./datasets";
import { ActivityBoard } from "./activity";
import { KnowledgeBoard, ManualExamplePanel, ReviewBoard } from "./knowledge";
export default function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [storage, setStorage] = useState<StorageStatus | null>(null);
  const [product, setProduct] = useState<ProductWorkspace | null>(null);
  const [reviewPage, setReviewPage] = useState<HistoryPage<ReviewRecord> | null>(null);
  const [jobPage, setJobPage] = useState<HistoryPage<JobRecord> | null>(null);
  const reviews = reviewPage?.items ?? [];
  const jobs = jobPage?.items ?? [];
  const [missions, setMissions] = useState<MissionRecord[]>([]);
  const [active, setActive] = useState("Misiones");
  const pageExitGuard = useRef<(() => boolean) | null>(null);
  const registerExitGuard = useCallback((guard: (() => boolean) | null) => { pageExitGuard.current = guard; }, []);
  const navigate = useCallback((page: string) => {
    if (page === active || (pageExitGuard.current && !pageExitGuard.current())) return;
    setActive(page);
  }, [active]);
  const [status, setStatus] = useState<"loading" | "ready" | "stale" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [suiteSelection, setSuiteSelection] = useState<SuiteSelection>({});
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setStatus("loading");
    setError(null);
    try {
      const [nextOverview, nextProduct, nextReviews, nextJobs, nextMissions] = await Promise.all([loadOverview(), loadProductWorkspace(), loadReviewsPage(), loadJobsPage(), loadMissions()]);
      setOverview(nextOverview);
      setProduct((current) => current ? mergeProductWorkspace(current, nextProduct, "refresh") : nextProduct);
      setReviewPage((current) => current ? mergeHistoryPage(current, nextReviews, "refresh", "review_id") : nextReviews);
      setJobPage((current) => current ? mergeHistoryPage(current, nextJobs, "refresh", "job_id") : nextJobs);
      setMissions(nextMissions);
      setStatus("ready");
    } catch (reason) {
      setStatus((current) => current === "ready" || current === "stale" ? "stale" : "error");
      setError(reason instanceof Error ? reason.message : "No se pudo leer el Coordinator.");
    }
  }, []);

  const revokeWorker = async (nodeId: string) => {
    if (!window.confirm("Este Worker perderá acceso a los trabajos y artefactos. ¿Revocar su credencial?")) return;
    try { await revokeNode(nodeId); await refresh(true); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No se pudo revocar el Worker."); setStatus("stale"); }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(true); }, 10000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (active !== "Configuración") return;
    const read = () => { void loadStorage().then(setStorage).catch(() => setStorage(null)); };
    read();
    const timer = window.setInterval(read, 60000);
    return () => window.clearInterval(timer);
  }, [active]);

  const evidenceCounts = useMemo(() => {
    const counts: Record<EvidenceStatus, number> = { tested: 0, detected: 0, pending: 0, blocked: 0 };
    overview?.evidence.forEach((item) => counts[item.status]++);
    return counts;
  }, [overview]);
  const missionChanged = useCallback((changed: MissionRecord) => setMissions((current) =>
    [changed, ...current.filter((item) => item.mission_id !== changed.mission_id)]), []);
  const selectedMission = missions.find((item) => item.mission_id === window.localStorage.getItem("local-ai-lab.selected-mission.v1"));
  const historyGroups = workspaceGroups.filter((group) => product?.pagination?.[group]?.has_more);
  const loadedHistory = workspaceGroups.reduce((total, group) => total + (product?.[group].length ?? 0), 0) + reviews.length + jobs.length;
  const totalHistory = workspaceGroups.reduce((total, group) => total +
    (product?.pagination?.[group]?.total ?? product?.[group].length ?? 0), 0) +
    (reviewPage?.pagination.total ?? reviews.length) + (jobPage?.pagination.total ?? jobs.length);
  const loadHistory = async () => {
    if (historyBusy || (!historyGroups.length && !reviewPage?.pagination.has_more && !jobPage?.pagination.has_more)) return;
    setHistoryBusy(true); setHistoryError(null);
    try {
      const [productNext, reviewsNext, jobsNext] = await Promise.all([
        historyGroups.length && product?.pagination ? loadMoreProductWorkspace(historyGroups,
          Object.fromEntries(historyGroups.map((group) =>
            [group, product.pagination?.[group]?.cursor ?? null]))) : Promise.resolve(null),
        reviewPage?.pagination.has_more ? loadReviewsPage(reviewPage.pagination.cursor) : Promise.resolve(null),
        jobPage?.pagination.has_more ? loadJobsPage(jobPage.pagination.cursor) : Promise.resolve(null),
      ]);
      if (productNext) setProduct((current) => current ? mergeProductWorkspace(current, productNext, "more") : productNext);
      if (reviewsNext) setReviewPage((current) => current ? mergeHistoryPage(current, reviewsNext, "more", "review_id") : reviewsNext);
      if (jobsNext) setJobPage((current) => current ? mergeHistoryPage(current, jobsNext, "more", "job_id") : jobsNext);
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : "No se pudo cargar más historial.");
    } finally { setHistoryBusy(false); }
  };

  return (
    <div className="app-shell guided-shell">
      <aside className="rail" aria-label="Navegación principal">
        <div className="brand"><span aria-hidden="true"><Hexagon size={28} strokeWidth={2.25} /></span><div><strong>Local AI Lab</strong><small>Entorno local · privado · v{APP_VERSION}</small></div></div>
        <nav>{["Misión actual", "Ejecución", "Observabilidad", "Configuración"].map((group) => <div className="nav-group" key={group}><p>{group}</p>{navigation.filter((item) => item.group === group).map((item) => {
          const Icon = item.icon;
          return (
          <button key={item.label} className={active === item.label ? "active" : ""} onClick={() => navigate(item.label)} aria-current={active === item.label ? "page" : undefined}>
            <Icon aria-hidden="true" size={19} strokeWidth={1.8} />{item.label}
          </button>
        )})}</div>)}</nav>
        <div className="privacy-note"><strong><ShieldCheck aria-hidden="true" size={17} /> Red local</strong><span>Comprueba el destino de cada job</span><small>El Coordinator puede enviar datos a Workers y al Broker configurado.</small></div>
      </aside>

      <main className="workspace">
        <header className="app-topbar">
          <div><small>Espacio de trabajo</small><strong>{overview?.phase.toUpperCase() ?? "LOCAL"}</strong></div>
          <div className="topbar-trust"><strong><ShieldCheck aria-hidden="true" size={17} /> Procesamiento en el laboratorio</strong><small>Los jobs pueden usar otros equipos de la red local.</small></div>
          {historyGroups.length || reviewPage?.pagination.has_more || jobPage?.pagination.has_more ? <button className="refresh" onClick={() => void loadHistory()} disabled={historyBusy} title="Cargar resultados antiguos en todas las secciones">{historyBusy ? "Cargando historial…" : `Cargar historial (${loadedHistory}/${totalHistory})`}</button> : null}
          {historyError ? <small role="status">{historyError}</small> : null}
          <button className="refresh" disabled={status === "loading"} onClick={() => void refresh()}><RefreshCw aria-hidden="true" size={16} />{status === "loading" ? "Actualizando…" : "Actualizar"}</button>
        </header>

        {status === "error" ? <ErrorState message={error ?? "Error desconocido"} retry={() => void refresh()} /> : null}
        {status === "loading" && !overview ? <LoadingState /> : null}
        {status === "stale" ? <StaleState message={error ?? "No se pudo actualizar"} retry={() => void refresh()} /> : null}
        {overview ? (
          <div className={status === "loading" ? "content scanning" : "content"} aria-busy={status === "loading"}>
            {active === "Misiones" ? <MissionBoard overview={overview} product={product} reviews={reviews} jobs={jobs} missions={missions} onChanged={missionChanged} onNavigate={navigate} /> : <>
              <header className="workspace-header"><div><p className="context">{active}</p><h1>{pageCopy[active].title}</h1><p>{pageCopy[active].description}</p></div></header>
              {active === "Evidencia" ? <section className="status-strip" aria-label="Resumen de evidencia">
                <StatusCount status="tested" label="Probado" count={evidenceCounts.tested} />
                <StatusCount status="detected" label="Detectado" count={evidenceCounts.detected} />
                <StatusCount status="pending" label="Pendiente" count={evidenceCounts.pending} />
                <StatusCount status="blocked" label="Bloqueado" count={evidenceCounts.blocked} />
              </section> : null}
              <section className="ledger" aria-labelledby="ledger-title">
              <div className="section-heading"><div><p>Coordinator · {formatTime(overview.observed_at)}</p><h2 id="ledger-title">{pageCopy[active].title}</h2></div><code>{active === "Evidencia" ? overview.schema_version : product?.schema_version ?? "workspace pendiente"}</code></div>
              {active === "Planes y borradores" ? <MissionList missions={missions} onOpen={(id) => { window.localStorage.setItem("local-ai-lab.selected-mission.v1", id); navigate("Misiones"); }} /> : null}
              {active === "Evidencia" ? <><EvidenceTable items={overview.evidence} /><NodeTable nodes={overview.nodes} onRevoke={(nodeId) => void revokeWorker(nodeId)} /></> : null}
              {active === "Recursos" ? <><KnowledgeBoard records={product?.knowledge ?? []} onCreated={(record) => setProduct((current) => current ? { ...current, knowledge: [record, ...current.knowledge] } : current)} /><NodeTable nodes={overview.nodes} onRevoke={(nodeId) => void revokeWorker(nodeId)} /></> : null}
              {active === "Experimentos" ? <>
                <SuiteContextPanel benchmarks={product?.benchmarks ?? []} knowledge={product?.knowledge ?? []} selection={suiteSelection} onChange={setSuiteSelection} />
                <ExperimentBoard records={[...(product?.benchmarks ?? []), ...(product?.experiments ?? [])]} knowledge={product?.knowledge ?? []} nodes={overview.nodes} selection={suiteSelection} onCreated={(record) => setProduct((current) => current ? record.category === "benchmark" ? { ...current, benchmarks: [record, ...current.benchmarks] } : { ...current, experiments: [record, ...current.experiments] } : current)} />
                <BrokerCompatibilityPanel onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} />
                <StrategyRunnerPanel records={product?.experiments ?? []} training={product?.training ?? []} nodes={overview.nodes} selection={suiteSelection} onSelectionChange={setSuiteSelection} onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} />
                <AgentExperimentPanel records={product?.experiments ?? []} nodes={overview.nodes} selection={suiteSelection} onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} />
                <StrategySelectorPanel records={product?.experiments ?? []} onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} />
              </> : null}
              {active === "Revisiones" ? <><ManualExamplePanel knowledge={product?.knowledge ?? []} onCreated={(review) => setReviewPage((current) => current ? { ...current, items: [review, ...current.items], pagination: { ...current.pagination, total: current.pagination.total + 1 } } : current)} /><ReviewBoard reviews={reviews} registerExitGuard={registerExitGuard} onRefresh={() => refresh(true)} onChanged={(changed) => setReviewPage((current) => current ? { ...current, items: current.items.map((item) => item.review_id === changed.review_id ? changed : item).sort((a, b) => b.updated_at.localeCompare(a.updated_at)) } : current)} /></> : null}
               {active === "Datasets" ? <DatasetBoard records={product?.datasets ?? []} reviews={reviews} snapshots={product?.knowledge ?? []} onCreated={(record) => { setProduct((current) => current ? { ...current, datasets: [record, ...current.datasets] } : current); void refresh(); }} /> : null}
              {active === "Entrenamientos" ? <><OperationsBoard records={[...(product?.training ?? []), ...(product?.exports ?? [])]} datasets={product?.datasets ?? []} experiments={product?.experiments ?? []} nodes={overview.nodes} jobs={jobs} onChanged={() => void refresh()} /><DistillationPanel mission={selectedMission} datasets={product?.datasets ?? []} preflights={(product?.training ?? []).filter((record) => record.status === "PREFLIGHT_PASSED")} experiments={product?.experiments ?? []} onChanged={() => void refresh()} /></> : null}
              {active === "Registros" || active === "Métricas" ? <ActivityBoard mode={active === "Registros" ? "runs" : "metrics"} jobs={jobs} nodes={overview.nodes} workspace={product} jobCounts={overview.job_counts} totalJobs={jobPage?.pagination.total ?? jobs.length} onRecovered={() => void refresh(true)} /> : null}
              {active === "Configuración" ? <><BrokerCompatibilityPanel onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} /><DependencySummary overview={overview} storage={storage} /><StorageCleanupPanel onCleaned={() => { void loadStorage().then(setStorage).catch(() => setStorage(null)); }} /></> : null}
            </section>
            </>}
          </div>
        ) : status === "ready" ? <EmptyState /> : null}
      </main>
    </div>
  );
}
