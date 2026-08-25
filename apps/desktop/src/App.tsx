/*
THESIS: Local AI Lab starts from the operator's goal and turns evidence into a guided mission.
OWN-WORLD: Mineral-white ruled surfaces, ink-green type, cobalt selection, semantic evidence stamps.
STORY: The operator chooses an outcome, sees the complete route, and always has one exact next action.
FIRST VIEWPORT: A compact mission rail, a complete training route, and a live plan preview.
FORM: Guided local-research workbench; existing evidence and expert controls remain reachable.
*/
import { useCallback, useEffect, useMemo, useState } from "react";
import { buildApprovedFeedbackDataset, cancelJob, changeReviewState, changeTrainingState, checkBrokerCompatibility, createBrokerAgentExperiment, createDistillationRun, createKnowledgeIndex, createModelExport, createSemanticRetrievalBenchmark, createStrategyRun, createTrainingPreflight, createTrainingRun, createVaultSnapshot, discoverVaults, loadJobs, loadOverview, loadProductWorkspace, loadReviews, registerRealBenchmark, runControlledRetrievalBenchmark, runModelDriftComparison, saveReviewCorrection, selectStrategy } from "./api";
import type { EvidenceItem, EvidenceStatus, JobRecord, Overview, ProductRecord, ProductWorkspace, ReviewRecord } from "./contracts";

const navigation = [
  { group: "Misión actual", label: "Misiones" },
  { group: "Misión actual", label: "Planes y borradores" },
  { group: "Misión actual", label: "Evidencia" },
  { group: "Misión actual", label: "Recursos" },
  { group: "Ejecución", label: "Experimentos" },
  { group: "Ejecución", label: "Revisiones" },
  { group: "Ejecución", label: "Datasets" },
  { group: "Ejecución", label: "Entrenamientos" },
  { group: "Configuración", label: "Configuración" },
];

const pageCopy: Record<string, { title: string; description: string }> = {
  Misiones: { title: "Quiero entrenar un modelo", description: "Elige una estrategia y construye un plan guiado de principio a fin." },
  "Planes y borradores": { title: "Planes y borradores", description: "Retoma recorridos, revisa resultados y continúa desde el último paso seguro." },
  Evidencia: { title: "Mesa de evidencia", description: "Lo probado, lo detectado y lo que todavía impide avanzar." },
  Recursos: { title: "Recursos del laboratorio", description: "Vaults, snapshots, índices y equipos disponibles para tus misiones." },
  Experimentos: { title: "Ensayos comparables", description: "Benchmarks y estrategias sobre la misma suite, snapshot y conjunto de casos." },
  Revisiones: { title: "Revisión humana", description: "Correcciones, diferencias y evidencia antes de aprobar cualquier dato de entrenamiento." },
  Datasets: { title: "Fábrica de datasets", description: "Ejemplos aprobados, deduplicados y aislados de todos los benchmarks." },
  Entrenamientos: { title: "Entrenamiento y exportación", description: "Pruebas cortas, trabajos recuperables y paquetes verificables." },
  Configuración: { title: "Entorno y dependencias", description: "Comprueba integraciones sin modificar sistemas externos ni persistir secretos." },
};

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
        <div className="brand"><span aria-hidden="true">L</span><div><strong>Local AI Lab</strong><small>Entorno local · privado</small></div></div>
        <nav>{["Misión actual", "Ejecución", "Configuración"].map((group) => <div className="nav-group" key={group}><p>{group}</p>{navigation.filter((item) => item.group === group).map((item) => (
          <button key={item.label} className={active === item.label ? "active" : ""} onClick={() => setActive(item.label)} aria-current={active === item.label ? "page" : undefined}>
            <span aria-hidden="true" className="nav-mark" />{item.label}
          </button>
        ))}</div>)}</nav>
        <div className="privacy-note"><strong>Entorno local activo</strong><span>Solo este equipo</span><small>Todo el procesamiento y la evidencia permanecen en el laboratorio.</small></div>
      </aside>

      <main className="workspace">
        <header className="app-topbar">
          <div><small>Espacio de trabajo</small><strong>{overview?.phase.toUpperCase() ?? "LOCAL"}</strong></div>
          <div className="topbar-trust"><strong>Todo se ejecuta en este equipo</strong><small>Ningún dato sale del entorno local.</small></div>
          <button className="refresh" disabled={status === "loading"} onClick={() => void refresh()}>{status === "loading" ? "Actualizando…" : "Actualizar"}</button>
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
              {active === "Configuración" ? <><BrokerCompatibilityPanel onCreated={(record) => setProduct((current) => current ? { ...current, experiments: [record, ...current.experiments] } : current)} /><DependencySummary overview={overview} /></> : null}
            </section>
            </>}
          </div>
        ) : status === "ready" ? <EmptyState /> : null}
      </main>
    </div>
  );
}

type MissionStrategy = "lora" | "rag" | "distillation" | "recommend";
type MissionDraft = Partial<{ strategy: MissionStrategy; task: string; success: string; constraints: string; teacherSource: "broker" | "local"; teacherModel: string; studentModel: string; created: boolean; activeStep: number; savedAt: string }>;

function readMissionDraft(): MissionDraft {
  try {
    const raw = window.localStorage.getItem("local-ai-lab.mission-draft.v1");
    return raw ? JSON.parse(raw) as MissionDraft : {};
  } catch { return {}; }
}

const missionStrategies: { id: MissionStrategy; title: string; badge: string; description: string }[] = [
  { id: "lora", title: "LoRA / SFT local", badge: "Disponible", description: "Especializa un modelo local con ejemplos aprobados y un adapter recuperable." },
  { id: "rag", title: "Fine-tuning + RAG", badge: "Disponible", description: "Combina comportamiento entrenado con conocimiento recuperado desde un snapshot." },
  { id: "distillation", title: "Destilación de otro LLM", badge: "Disponible", description: "Un modelo profesor genera respuestas supervisadas para entrenar un modelo alumno más pequeño." },
  { id: "recommend", title: "Que la app recomiende", badge: "Compara alternativas", description: "Usa evidencia comparable para elegir la solución menos compleja que cumpla el objetivo." },
];

const missionFlows: Record<MissionStrategy, { title: string; input: string; output: string; destination?: string }[]> = {
  lora: [
    { title: "Definir objetivo", input: "Qué debe aprender", output: "Hipótesis medible" },
    { title: "Elegir modelo y datos", input: "Modelo y dataset", output: "Combinación fijada", destination: "Datasets" },
    { title: "Validar entorno", input: "Nodo y modelo", output: "Preflight aprobado", destination: "Entrenamientos" },
    { title: "Entrenar", input: "Plan autorizado", output: "Adapter LoRA", destination: "Entrenamientos" },
    { title: "Comparar", input: "Baseline definido", output: "Evidencia comparable", destination: "Experimentos" },
    { title: "Exportar", input: "Resultado validado", output: "Paquete verificable", destination: "Entrenamientos" },
  ],
  rag: [
    { title: "Definir objetivo", input: "Tarea y límites", output: "Criterio de éxito" },
    { title: "Preparar conocimiento", input: "Vault permitido", output: "Snapshot e índice", destination: "Recursos" },
    { title: "Preparar dataset", input: "Ejemplos aprobados", output: "Dataset versionado", destination: "Datasets" },
    { title: "Entrenar", input: "Modelo y preflight", output: "Adapter LoRA", destination: "Entrenamientos" },
    { title: "Evaluar con RAG", input: "Adapter e índice", output: "Comparación F1/F2", destination: "Experimentos" },
    { title: "Exportar", input: "Estrategia validada", output: "Modelo e informe", destination: "Entrenamientos" },
  ],
  distillation: [
    { title: "Definir objetivo", input: "Qué y por qué", output: "Objetivo claro" },
    { title: "Elegir profesor y alumno", input: "Broker o profesor local + alumno local", output: "Pareja fijada" },
    { title: "Preparar y aprobar dataset", input: "Prompts autorizados", output: "Dataset aprobado", destination: "Datasets" },
    { title: "Validar permisos y entorno", input: "Términos, PEFT y hardware", output: "Entorno listo", destination: "Recursos" },
    { title: "Destilar", input: "Dataset y modelos", output: "Modelo alumno", destination: "Entrenamientos" },
    { title: "Comparar con baseline", input: "Baseline definido", output: "Resultados comparativos", destination: "Experimentos" },
    { title: "Exportar", input: "Modelo y reporte", output: "Paquete exportable", destination: "Entrenamientos" },
  ],
  recommend: [
    { title: "Definir necesidad", input: "Tarea y restricciones", output: "Criterios medibles" },
    { title: "Preparar casos", input: "Casos representativos", output: "Suite comparable", destination: "Experimentos" },
    { title: "Ejecutar alternativas", input: "Modelos y estrategias", output: "Resultados homogéneos", destination: "Experimentos" },
    { title: "Revisar evidencia", input: "Métricas y respuestas", output: "Resultados aprobados", destination: "Revisiones" },
    { title: "Elegir estrategia", input: "Restricciones reales", output: "Recomendación explicada", destination: "Experimentos" },
  ],
};

function MissionBoard({ overview, product, onNavigate }: { overview: Overview; product: ProductWorkspace | null; onNavigate: (page: string) => void }) {
  const [strategy, setStrategy] = useState<MissionStrategy>("distillation");
  const [activeStep, setActiveStep] = useState(0);
  const [created, setCreated] = useState(false);
  const [task, setTask] = useState("");
  const [success, setSuccess] = useState("");
  const [constraints, setConstraints] = useState("");
  const [teacherSource, setTeacherSource] = useState<"broker" | "local">("broker");
  const [teacherModel, setTeacherModel] = useState("");
  const [studentModel, setStudentModel] = useState("");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const flow = missionFlows[strategy];
  const current = flow[activeStep] ?? flow[0];
  const blockers = [
    product?.datasets.length ? null : "Falta un dataset aprobado",
    overview.nodes.length ? null : "Falta un Worker registrado",
    strategy === "distillation" && !teacherModel.trim() ? "Falta elegir el modelo profesor" : null,
    strategy === "distillation" && !studentModel.trim() ? "Falta elegir el modelo alumno" : null,
  ].filter((item): item is string => Boolean(item));

  useEffect(() => {
    const draft = readMissionDraft();
    if (draft.strategy && missionFlows[draft.strategy]) setStrategy(draft.strategy);
    setTask(draft.task ?? ""); setSuccess(draft.success ?? ""); setConstraints(draft.constraints ?? "");
    setTeacherSource(draft.teacherSource ?? "broker"); setTeacherModel(draft.teacherModel ?? ""); setStudentModel(draft.studentModel ?? "");
    setCreated(Boolean(draft.created)); setActiveStep(Math.max(0, Number(draft.activeStep ?? 0))); setSavedAt(draft.savedAt ?? null);
  }, []);

  const saveDraft = useCallback(() => {
    const timestamp = new Date().toISOString();
    window.localStorage.setItem("local-ai-lab.mission-draft.v1", JSON.stringify({ strategy, task, success, constraints, teacherSource, teacherModel, studentModel, created, activeStep, savedAt: timestamp }));
    setSavedAt(timestamp);
  }, [strategy, task, success, constraints, teacherSource, teacherModel, studentModel, created, activeStep]);

  useEffect(() => {
    if (!created) return;
    const handle = window.setTimeout(saveDraft, 500);
    return () => window.clearTimeout(handle);
  }, [created, saveDraft]);

  const chooseStrategy = (next: MissionStrategy) => { setStrategy(next); setActiveStep(0); setCreated(false); };
  const createPlan = () => { setCreated(true); setActiveStep(0); window.setTimeout(saveDraft, 0); };
  const continueFlow = () => {
    if (current.destination) { onNavigate(current.destination); return; }
    setActiveStep((value) => Math.min(flow.length - 1, value + 1));
  };

  return <section className="mission-board" aria-labelledby="mission-title">
    <header className="mission-heading"><div><p className="context">Misión actual</p><h1 id="mission-title">Quiero entrenar un modelo</h1><p>Elige una estrategia para construir tu plan guiado paso a paso.</p></div><div className="draft-state"><strong>{savedAt ? "Borrador guardado" : "Nuevo plan"}</strong><small>{savedAt ? formatTime(savedAt) : "Se guardará automáticamente"}</small></div></header>
    <div className="strategy-start"><div><h2>¿Cómo quieres conseguirlo?</h2><div className="strategy-list">{missionStrategies.map((item) => <button key={item.id} className={strategy === item.id ? "selected" : ""} onClick={() => chooseStrategy(item.id)} aria-pressed={strategy === item.id}><span><strong>{item.title}</strong><small>{item.description}</small></span><b>{item.badge}</b></button>)}</div><button className="primary-action" onClick={createPlan}>{created ? "Recrear plan guiado" : "Crear plan guiado"}</button></div><div className="strategy-explainer"><strong>{missionStrategies.find((item) => item.id === strategy)?.title}</strong><p>{missionStrategies.find((item) => item.id === strategy)?.description}</p>{strategy === "distillation" ? <div className="capability-note"><strong>Destilación secuencial profesor → alumno disponible</strong><span>El profesor puede ejecutarse mediante AI Broker o desde la caché local. El alumno siempre se entrena localmente con LoRA y después se compara contra el baseline.</span></div> : null}</div></div>
    <ol className="mission-flow" aria-label="Recorrido completo">{flow.map((step, index) => <li key={step.title} className={index === activeStep ? "active" : index < activeStep ? "complete" : ""}><button onClick={() => created && setActiveStep(index)} disabled={!created}><span>{index + 1}</span><strong>{step.title}</strong><small>Entrada: {step.input}</small><small>Salida: {step.output}</small></button></li>)}</ol>
    <div className="mission-workbench"><section className="step-workspace"><div className="step-title"><span>{activeStep + 1}</span><div><h2>{current.title}</h2><p>{activeStep === 0 ? "Define qué debe aprender el modelo, cómo sabrás que tuvo éxito y qué límites debe respetar." : `Completa esta etapa para producir: ${current.output}.`}</p></div></div>{activeStep === 0 ? <div className="mission-fields"><label><span>Tarea que debe aprender</span><textarea value={task} onChange={(event) => setTask(event.target.value)} placeholder="Describe la tarea o comportamiento que el modelo alumno debe dominar." /></label><label><span>Criterio de éxito</span><textarea value={success} onChange={(event) => setSuccess(event.target.value)} placeholder="Indica una medida verificable frente al baseline." /></label><label><span>Restricciones</span><textarea value={constraints} onChange={(event) => setConstraints(event.target.value)} placeholder="Datos excluidos, idiomas, latencia, permisos de uso o límites de privacidad." /></label></div> : strategy === "distillation" && activeStep === 1 ? <div className="mission-fields two-columns"><label><span>Dónde está el profesor</span><select value={teacherSource} onChange={(event) => setTeacherSource(event.target.value as "broker" | "local")}><option value="broker">AI Broker</option><option value="local">Caché local del Worker</option></select></label><label><span>{teacherSource === "broker" ? "Modelo profesor en AI Broker" : "Modelo profesor local"}</span><input value={teacherModel} onChange={(event) => setTeacherModel(event.target.value)} placeholder={teacherSource === "broker" ? "Nombre exacto anunciado por el Broker" : "Ruta o ID ya presente en caché"} /></label><label><span>Modelo alumno local</span><input value={studentModel} onChange={(event) => setStudentModel(event.target.value)} placeholder="Ruta o ID ya presente en caché" /></label></div> : <div className="step-guidance"><strong>Qué ocurrirá aquí</strong><p>La aplicación abrirá las herramientas necesarias con el contexto del plan y conservará la evidencia producida para poder reanudar el recorrido.</p></div>}<footer><button className="secondary-action" onClick={saveDraft}>Guardar borrador</button><button className="primary-action" disabled={!created || (activeStep === 0 && (!task.trim() || !success.trim()))} onClick={continueFlow}>{current.destination ? `Abrir ${current.destination}` : activeStep === flow.length - 1 ? "Revisar resultado" : "Continuar"}</button></footer></section>
      <aside className="plan-preview"><h2>Vista previa del plan</h2><dl><div><dt>Estrategia</dt><dd>{missionStrategies.find((item) => item.id === strategy)?.title}</dd></div>{strategy === "distillation" ? <><div><dt>Origen del profesor</dt><dd>{teacherSource === "broker" ? "AI Broker" : "Worker local"}</dd></div><div><dt>Modelo profesor</dt><dd>{teacherModel || "Sin definir"}</dd></div><div><dt>Modelo alumno</dt><dd>{studentModel || "Sin definir"}</dd></div></> : null}<div><dt>Datasets disponibles</dt><dd>{product?.datasets.length ?? 0}</dd></div><div><dt>Workers registrados</dt><dd>{overview.nodes.length}</dd></div><div><dt>Límite de privacidad</dt><dd>Solo este equipo</dd></div><div><dt>Bloqueadores detectados</dt><dd className={blockers.length ? "pending" : "tested"}>{blockers.length || "Ninguno"}</dd></div></dl>{blockers.length ? <ul>{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul> : null}<div className="expected-result"><strong>Resultado final esperado</strong><span>{strategy === "distillation" ? "Modelo alumno validado + informe comparativo + paquete exportable" : "Modelo validado + evidencia comparable + paquete exportable"}</span></div></aside></div>
  </section>;
}

function DependencySummary({ overview }: { overview: Overview }) {
  return <section className="dependency-summary"><h3>Dependencias externas</h3><dl className="dependencies"><div><dt>AI Broker</dt><dd>{overview.external_dependencies.ai_broker}</dd></div><div><dt>Vault</dt><dd>{overview.external_dependencies.vault}</dd></div><div><dt>Model Drift</dt><dd>{overview.external_dependencies.model_drift}</dd></div></dl><div className="truth-note"><strong>Sin suposiciones silenciosas</strong><p>“Unknown” significa pendiente de prueba, no ausente ni incompatible.</p></div></section>;
}

function StatusCount({ status, label, count }: { status: EvidenceStatus; label: string; count: number }) {
  return <div className={`status-count ${status}`}><span aria-hidden="true" /> <strong>{label}</strong><b>{count}</b></div>;
}

function EvidenceTable({ items }: { items: EvidenceItem[] }) {
  return <div className="table-wrap"><table><caption>Evidencia necesaria para cerrar la fase actual</caption><thead><tr><th>Control</th><th>Estado</th><th>Procedencia recuperable</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.label}</td><td><span className={`stamp ${item.status}`}>{statusLabel(item.status)}</span></td><td>{item.artifact_sha256 ? <><code title={item.artifact_sha256}>sha256:{item.artifact_sha256.slice(0, 12)}…</code><small>{item.source_reference}</small><small>{item.observed_at ? formatTime(item.observed_at) : null}</small></> : <span className="not-recorded">Aún no registrada</span>}</td></tr>)}</tbody></table></div>;
}

function NodeTable({ nodes }: { nodes: Overview["nodes"] }) {
  return <section className="nodes-section"><h3>Nodos registrados</h3>{nodes.length ? <div className="table-wrap"><table><thead><tr><th>Equipo</th><th>Estado</th><th>Capacidades</th><th>Último heartbeat</th></tr></thead><tbody>{nodes.map((node) => <tr key={node.node_id}><td><strong>{node.hostname}</strong><code>{node.node_id}</code></td><td>{node.status}</td><td><span className={`stamp ${node.tested_workloads.length ? "tested" : node.capabilities_observed ? "detected" : "pending"}`}>{node.tested_workloads.length ? "PROBADAS" : node.capabilities_observed ? "DETECTADAS" : "PENDIENTES"}</span>{node.tested_workloads.length ? <small>{node.tested_workloads.join(" · ")}</small> : null}</td><td>{formatTime(node.last_heartbeat_at)}</td></tr>)}</tbody></table></div> : <p className="empty-row">No hay nodos reales registrados. El sistema no mostrará workers simulados como evidencia.</p>}</section>;
}

function RecordBoard({ records, emptyTitle, emptyText }: { records: ProductRecord[]; emptyTitle: string; emptyText: string }) {
  if (!records.length) return <div className="record-empty"><span aria-hidden="true">◇</span><div><strong>{emptyTitle}</strong><p>{emptyText}</p></div></div>;
  return <div className="record-grid">{records.map((record) => <article className="record-card" key={record.record_id}><div className="record-card-head"><span className="record-kind">{record.category}</span><span className={`stamp ${recordStatus(record.status)}`}>{record.status}</span></div><h3>{record.title}</h3><dl>{summaryRows(record.summary).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value}</dd></div>)}</dl><footer><code title={record.artifact_sha256}>sha256:{record.artifact_sha256.slice(0, 12)}…</code><time>{formatTime(record.updated_at)}</time></footer></article>)}</div>;
}

function ExperimentBoard({ records, snapshots, nodes, onCreated }: { records: ProductRecord[]; snapshots: ProductRecord[]; nodes: Overview["nodes"]; onCreated: (record: ProductRecord) => void }) {
  const [k, setK] = useState(5);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [semanticStrategy, setSemanticStrategy] = useState<"R2" | "R3" | "R4">("R2");
  const [semanticNode, setSemanticNode] = useState(nodes[0]?.node_id ?? "");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [embeddingFingerprint, setEmbeddingFingerprint] = useState("");
  const [embeddingDevice, setEmbeddingDevice] = useState("cpu");
  const [realDefinition, setRealDefinition] = useState("");
  const [r3Id, setR3Id] = useState("");
  const [r4Id, setR4Id] = useState("");
  const [driftExecutable, setDriftExecutable] = useState("");
  const [driftDirectory, setDriftDirectory] = useState("");
  const [driftConfirmed, setDriftConfirmed] = useState(false);
  const run = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await runControlledRetrievalBenchmark(k);
      onCreated(record);
      setMessage(record.status === "LOCAL_VERIFIED" ? "R1 ejecutado sobre ground truth aprobado." : "R1 ejecutado; el informe queda pendiente de revisión humana del ground truth.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "No se pudo ejecutar el benchmark.");
    } finally { setBusy(false); }
  };
  const runSemantic = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await createSemanticRetrievalBenchmark({ strategyId: semanticStrategy, nodeId: semanticNode, embeddingModel, embeddingModelFingerprint: embeddingFingerprint, device: embeddingDevice, k });
      onCreated(record);
      setMessage(`${semanticStrategy} enviado al Worker. El modelo se carga únicamente desde su caché local.`);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear el benchmark semántico."); }
    finally { setBusy(false); }
  };
  const prepareRealTemplate = () => {
    const snapshot = snapshots[0];
    if (!snapshot) { setMessage("Crea primero un snapshot COMPLETE del vault."); return; }
    setRealDefinition(JSON.stringify({ schema_version: "real-benchmark.v1", purpose: "external_validity", training_eligible: false, snapshot_hash: snapshot.artifact_sha256, human_review: { status: "approved", reviewer_kind: "human", reviewer: "" }, cases: [{ case_id: "real-001", query: "", reference_answer: { author_kind: "human", author: "", answer: "", evidence: [{ note_id: "", note_path: "", section: "", chunk_id: "", source_reference: `snapshot:sha256:${snapshot.artifact_sha256}#chunk:` }] } }] }, null, 2));
  };
  const saveReal = async () => {
    setBusy(true); setMessage(null);
    try {
      const parsed: unknown = JSON.parse(realDefinition);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("La definición debe ser un objeto JSON.");
      const record = await registerRealBenchmark(parsed as Record<string, unknown>);
      onCreated(record); setMessage("Benchmark real validado, ligado al snapshot y registrado como no entrenable.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo registrar el benchmark real."); }
    finally { setBusy(false); }
  };
  const compareFormal = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await runModelDriftComparison({ r3ExperimentId: r3Id, r4ExperimentId: r4Id, executable: driftExecutable, workingDirectory: driftDirectory, confirmed: driftConfirmed });
      onCreated(record); setMessage("Model Drift devolvió un informe formal asociado a R3 y R4.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo ejecutar Model Drift."); }
    finally { setBusy(false); }
  };
  const experimentRecords = records.filter((record) => record.category === "experiment" || record.category === "comparison");
  const r3Runs = records.filter((record) => record.status === "EXPERIMENT_SUCCEEDED" && record.summary.strategy_id === "R3");
  const r4Runs = records.filter((record) => record.status === "EXPERIMENT_SUCCEEDED" && record.summary.strategy_id === "R4");
  return <><div className="operation-forms experiment-forms"><fieldset><legend>R1 · baseline lexical</legend><label><span>Profundidad de retrieval (k)</span><input type="number" min={1} max={100} value={k} onChange={(event) => setK(Math.max(1, Math.min(100, Number(event.target.value))))} disabled={busy} /></label><button onClick={() => void run()} disabled={busy}>{busy ? "Trabajando…" : "Ejecutar R1 controlado"}</button><p>Se ejecuta localmente sobre un snapshot sintético; no usa AI Broker ni el vault real.</p></fieldset><fieldset><legend>R2–R4 · retrieval con embeddings</legend><label><span>Estrategia</span><select value={semanticStrategy} onChange={(event) => setSemanticStrategy(event.target.value as "R2" | "R3" | "R4")}><option value="R2">R2 · semántico</option><option value="R3">R3 · híbrido</option><option value="R4">R4 · híbrido + grafo</option></select></label><label><span>Worker</span><select value={semanticNode} onChange={(event) => setSemanticNode(event.target.value)}><option value="">Selecciona</option>{nodes.map((node) => <option key={node.node_id} value={node.node_id}>{node.hostname}</option>)}</select></label><label><span>Modelo de embeddings local exacto</span><input value={embeddingModel} onChange={(event) => setEmbeddingModel(event.target.value)} placeholder="ruta o ID ya presente en caché" /></label><label><span>SHA-256 del modelo/cache</span><input value={embeddingFingerprint} onChange={(event) => setEmbeddingFingerprint(event.target.value.toLowerCase())} maxLength={64} /></label><label><span>Dispositivo probado</span><input value={embeddingDevice} onChange={(event) => setEmbeddingDevice(event.target.value)} placeholder="cpu, cuda o mps" /></label><button onClick={() => void runSemantic()} disabled={busy || !semanticNode || !embeddingModel.trim() || !/^[0-9a-f]{64}$/.test(embeddingFingerprint) || !embeddingDevice.trim()}>Enviar benchmark</button><p>El Worker debe publicar <code>embeddings.semantic</code> como probado; no se descarga ningún modelo.</p></fieldset><fieldset className="wide-fieldset"><legend>Benchmark A · vault real</legend><p>La referencia debe estar escrita y aprobada por una persona; la aplicación valida cada evidencia contra un snapshot completo.</p><button onClick={prepareRealTemplate} disabled={busy || snapshots.length === 0}>Preparar plantilla del snapshot</button><label><span>Definición revisada</span><textarea className="definition-editor" value={realDefinition} onChange={(event) => setRealDefinition(event.target.value)} spellCheck={false} placeholder="Prepara la plantilla y completa consulta, autor, respuesta y evidencias." /></label><button onClick={() => void saveReal()} disabled={busy || !realDefinition.trim()}>Validar y registrar benchmark real</button></fieldset><fieldset className="wide-fieldset"><legend>Evaluación formal · Model Drift</legend><label><span>R3 completado</span><select value={r3Id} onChange={(event) => setR3Id(event.target.value)}><option value="">Selecciona</option>{r3Runs.map((item) => <option key={item.record_id} value={item.record_id}>{item.record_id.slice(0, 8)} · {String(item.summary.suite_fingerprint).slice(0, 8)}</option>)}</select></label><label><span>R4 completado</span><select value={r4Id} onChange={(event) => setR4Id(event.target.value)}><option value="">Selecciona</option>{r4Runs.map((item) => <option key={item.record_id} value={item.record_id}>{item.record_id.slice(0, 8)} · {String(item.summary.suite_fingerprint).slice(0, 8)}</option>)}</select></label><label><span>Ejecutable público de Model Drift</span><input value={driftExecutable} onChange={(event) => setDriftExecutable(event.target.value)} /></label><label><span>Carpeta de Model Drift</span><input value={driftDirectory} onChange={(event) => setDriftDirectory(event.target.value)} /></label><label className="confirmation"><input type="checkbox" checked={driftConfirmed} onChange={(event) => setDriftConfirmed(event.target.checked)} /><span>Confirmo la ejecución externa mediante el CLI público; no se leerá su base de datos.</span></label><button onClick={() => void compareFormal()} disabled={busy || !r3Id || !r4Id || !driftExecutable.trim() || !driftDirectory.trim() || !driftConfirmed}>Ejecutar comparación formal</button></fieldset></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}{experimentRecords.length ? <ComparisonTable records={experimentRecords} /> : <RecordBoard records={[]} emptyTitle="Todavía no hay ensayos comparables" emptyText="Ejecuta R1 y después R2–R4 con un Worker y modelo local probados." />}</>;
}

function ComparisonTable({ records }: { records: ProductRecord[] }) {
  return <div className="table-wrap comparison-table"><table><caption>Trade-offs por estrategia, sin score global</caption><thead><tr><th>Estrategia</th><th>Calidad retrieval</th><th>Coste</th><th>Privacidad</th><th>Estado formal</th><th>Evidencia</th></tr></thead><tbody>{records.map((record) => <tr key={record.record_id}><td><strong>{String(record.summary.strategy_id ?? record.title)}</strong><small>{record.status}</small></td><td><span>Recall@k {formatMetric(record.summary.recall_at_k)}</span><small>Precision {formatMetric(record.summary.precision_at_k)} · MRR {formatMetric(record.summary.mrr)} · nDCG {formatMetric(record.summary.ndcg_at_k)}</small></td><td>{String(record.summary.cost ?? "unknown")}</td><td>{String(record.summary.privacy ?? "unknown")}</td><td>{String(record.summary.formal_status ?? "unverified")}</td><td><code title={record.artifact_sha256}>sha256:{record.artifact_sha256.slice(0, 12)}…</code></td></tr>)}</tbody></table></div>;
}

function BrokerCompatibilityPanel({ onCreated }: { onCreated: (record: ProductRecord) => void }) {
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8000");
  const [token, setToken] = useState("");
  const [phase, setPhase] = useState<"phase0" | "retrieval" | "formal_evaluation" | "agent_experiments">("phase0");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const inspect = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await checkBrokerCompatibility({ endpoint, phase, token });
      onCreated(record);
      setMessage(record.status === "UPGRADE_REQUIRED" ? "La capacidad observada no cubre esta fase. Instala un Broker que anuncie las capacidades ausentes del informe." : `Comprobación read-only terminada: ${record.status}.`);
      setToken("");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo negociar con AI Broker."); }
    finally { setBusy(false); }
  };
  return <section className="broker-panel"><h3>AI Broker · negociación read-only</h3><div className="knowledge-controls"><label><span>Endpoint local</span><input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} /></label><label><span>Fase a comprobar</span><select value={phase} onChange={(event) => setPhase(event.target.value as typeof phase)}><option value="phase0">Conectividad básica</option><option value="retrieval">Generación RAG</option><option value="formal_evaluation">Evaluación formal 2.9</option><option value="agent_experiments">A1 + M1 (2.9)</option></select></label><label><span>Token efímero (si hace falta)</span><input type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" /></label><button onClick={() => void inspect()} disabled={busy || !endpoint.trim()}>{busy ? "Consultando…" : "Consultar health + capabilities"}</button><p>Solo GET sobre <code>/health</code> y <code>/api/v1/capabilities</code>. El token no se persiste.</p></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}</section>;
}

function StrategySelectorPanel({ records, onCreated }: { records: ProductRecord[]; onCreated: (record: ProductRecord) => void }) {
  const eligible = records.filter((record) => Array.isArray(record.summary.case_ids) && typeof record.summary.recall_at_k === "number");
  const [selected, setSelected] = useState<string[]>([]);
  const [minimumCases, setMinimumCases] = useState(20);
  const [formal, setFormal] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const toggle = (id: string) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const decide = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await selectStrategy({ experimentIds: selected, privacy: "local_only", minimumCases, requireFormalVerdict: formal });
      onCreated(record); setMessage(`${record.status}: ${String(record.summary.uncertainty)}`);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo evaluar la selección."); }
    finally { setBusy(false); }
  };
  return <section className="selector-panel"><h3>Selector de estrategia · recomendación explicable</h3><p>No se activa hasta que existan resultados comparables y conserva la incertidumbre.</p><div className="selector-options">{eligible.map((record) => <label key={record.record_id}><input type="checkbox" checked={selected.includes(record.record_id)} onChange={() => toggle(record.record_id)} /><span>{String(record.summary.strategy_id)} · {record.record_id.slice(0, 8)}</span></label>)}</div><div className="knowledge-controls"><label><span>Mínimo de casos comparables</span><input type="number" min={1} value={minimumCases} onChange={(event) => setMinimumCases(Math.max(1, Number(event.target.value)))} /></label><label className="confirmation"><input type="checkbox" checked={formal} onChange={(event) => setFormal(event.target.checked)} /><span>Exigir veredicto formal de Model Drift</span></label><button onClick={() => void decide()} disabled={busy || selected.length < 2}>{busy ? "Evaluando…" : "Generar recomendación"}</button></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}</section>;
}

function AgentExperimentPanel({ records, nodes, onCreated }: { records: ProductRecord[]; nodes: Overview["nodes"]; onCreated: (record: ProductRecord) => void }) {
  const checks = records.filter((record) => record.status === "CAPABILITIES_SATISFIED" && record.summary.phase === "agent_experiments");
  const [strategyId, setStrategyId] = useState<"A1" | "M1">("A1");
  const [checkId, setCheckId] = useState("");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8000");
  const [nodeId, setNodeId] = useState(nodes[0]?.node_id ?? "");
  const [provider, setProvider] = useState("");
  const [deployment, setDeployment] = useState("");
  const [model, setModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [embeddingFingerprint, setEmbeddingFingerprint] = useState("");
  const [device, setDevice] = useState("cpu");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await createBrokerAgentExperiment({ strategyId, brokerCheckId: checkId, brokerEndpoint: endpoint, nodeId, provider, deployment, model, embeddingModel, embeddingModelFingerprint: embeddingFingerprint, device, k: 5 });
      onCreated(record); setMessage(`${strategyId} enviado con modelo exacto, frontera local_only y sin fallback.`);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear el experimento A1/M1."); }
    finally { setBusy(false); }
  };
  return <section className="agent-panel"><h3>A1 / M1 · AI Broker + RAG</h3><p>Local AI Lab resuelve la herramienta de retrieval; AI Broker conserva su runtime agent/mixture. El Worker toma el token desde su almacén local, nunca desde el job.</p><div className="operation-forms"><fieldset><legend>Contrato y ejecución</legend><label><span>Estrategia</span><select value={strategyId} onChange={(event) => setStrategyId(event.target.value as "A1" | "M1")}><option value="A1">A1 · agent + tool retrieval</option><option value="M1">M1 · mixture_of_agents + RAG</option></select></label><label><span>Informe Broker 2.9 satisfecho</span><select value={checkId} onChange={(event) => setCheckId(event.target.value)}><option value="">Selecciona</option>{checks.map((item) => <option key={item.record_id} value={item.record_id}>{item.record_id.slice(0, 8)} · {String(item.summary.observed_contract)}</option>)}</select></label><label><span>Endpoint</span><input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} /></label><label><span>Worker</span><select value={nodeId} onChange={(event) => setNodeId(event.target.value)}><option value="">Selecciona</option>{nodes.map((node) => <option key={node.node_id} value={node.node_id}>{node.hostname}</option>)}</select></label></fieldset><fieldset><legend>Modelos exactos locales</legend><label><span>Proveedor</span><input value={provider} onChange={(event) => setProvider(event.target.value)} /></label><label><span>Deployment</span><input value={deployment} onChange={(event) => setDeployment(event.target.value)} /></label><label><span>Modelo</span><input value={model} onChange={(event) => setModel(event.target.value)} /></label><label><span>Modelo embeddings cacheado</span><input value={embeddingModel} onChange={(event) => setEmbeddingModel(event.target.value)} /></label><label><span>SHA-256 embeddings</span><input value={embeddingFingerprint} onChange={(event) => setEmbeddingFingerprint(event.target.value.toLowerCase())} maxLength={64} /></label><label><span>Dispositivo</span><input value={device} onChange={(event) => setDevice(event.target.value)} /></label><button onClick={() => void run()} disabled={busy || !checkId || !nodeId || !endpoint.trim() || !provider.trim() || !deployment.trim() || !model.trim() || !embeddingModel.trim() || !/^[0-9a-f]{64}$/.test(embeddingFingerprint)}>{busy ? "Enviando…" : "Ejecutar suite A1/M1"}</button></fieldset></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}</section>;
}

function StrategyRunnerPanel({ records, training, nodes, onCreated }: { records: ProductRecord[]; training: ProductRecord[]; nodes: Overview["nodes"]; onCreated: (record: ProductRecord) => void }) {
  const checks = records.filter((record) => record.status === "CAPABILITIES_SATISFIED" && record.summary.phase === "retrieval");
  const trained = training.filter((record) => record.status === "TRAINING_SUCCEEDED");
  const [strategyId, setStrategyId] = useState("B0");
  const [checkId, setCheckId] = useState("");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:8000");
  const [nodeId, setNodeId] = useState(nodes[0]?.node_id ?? "");
  const [provider, setProvider] = useState("");
  const [deployment, setDeployment] = useState("");
  const [model, setModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [embeddingFingerprint, setEmbeddingFingerprint] = useState("");
  const [device, setDevice] = useState("cpu");
  const [trainingId, setTrainingId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const semantic = new Set(["R2", "R3", "R4", "L1", "F2"]).has(strategyId);
  const fineTuned = new Set(["F1", "F2"]).has(strategyId);
  const run = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await createStrategyRun({ strategyId, brokerCheckId: checkId, brokerEndpoint: endpoint, nodeId, provider, deployment, model, embeddingModel: semantic ? embeddingModel : undefined, embeddingModelFingerprint: semantic ? embeddingFingerprint : undefined, device, trainingJobId: fineTuned ? trainingId : undefined, k: 5 });
      onCreated(record); setMessage(`${strategyId} enviado sobre la misma suite y snapshot, con modelo exacto y local_only.`);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear la ejecución de estrategia."); }
    finally { setBusy(false); }
  };
  return <section className="strategy-runner"><h3>B0–F2 · contrato común de estrategia</h3><p>Estas ejecuciones generan respuestas, verificación determinista, retrieval, latencia, coste y candidatos revisables; no confunden retrieval con calidad final.</p><div className="operation-forms"><fieldset><legend>Estrategia y evidencia</legend><label><span>Estrategia</span><select value={strategyId} onChange={(event) => setStrategyId(event.target.value)}>{["B0", "B1", "R1", "R2", "R3", "R4", "L1", "F1", "F2"].map((value) => <option key={value}>{value}</option>)}</select></label><label><span>Informe Broker retrieval satisfecho</span><select value={checkId} onChange={(event) => setCheckId(event.target.value)}><option value="">Selecciona</option>{checks.map((item) => <option key={item.record_id} value={item.record_id}>{item.record_id.slice(0, 8)} · {String(item.summary.observed_contract)}</option>)}</select></label><label><span>Worker</span><select value={nodeId} onChange={(event) => setNodeId(event.target.value)}><option value="">Selecciona</option>{nodes.map((node) => <option key={node.node_id} value={node.node_id}>{node.hostname}</option>)}</select></label><label><span>Endpoint Broker</span><input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} /></label>{fineTuned ? <label><span>Training Local AI Lab</span><select value={trainingId} onChange={(event) => setTrainingId(event.target.value)}><option value="">Selecciona</option>{trained.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label> : null}</fieldset><fieldset><legend>Modelo exacto</legend><label><span>Proveedor</span><input value={provider} onChange={(event) => setProvider(event.target.value)} /></label><label><span>Deployment</span><input value={deployment} onChange={(event) => setDeployment(event.target.value)} /></label><label><span>Modelo</span><input value={model} onChange={(event) => setModel(event.target.value)} /></label>{semantic ? <><label><span>Modelo embeddings cacheado</span><input value={embeddingModel} onChange={(event) => setEmbeddingModel(event.target.value)} /></label><label><span>SHA-256 embeddings</span><input value={embeddingFingerprint} onChange={(event) => setEmbeddingFingerprint(event.target.value.toLowerCase())} maxLength={64} /></label><label><span>Dispositivo</span><input value={device} onChange={(event) => setDevice(event.target.value)} /></label></> : null}<button onClick={() => void run()} disabled={busy || !checkId || !nodeId || !provider.trim() || !deployment.trim() || !model.trim() || (semantic && (!embeddingModel.trim() || !/^[0-9a-f]{64}$/.test(embeddingFingerprint))) || (fineTuned && !trainingId)}>{busy ? "Enviando…" : "Ejecutar estrategia"}</button></fieldset></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}</section>;
}

function DatasetBoard({ records, approvedCount, onCreated }: { records: ProductRecord[]; approvedCount: number; onCreated: (record: ProductRecord) => void }) {
  const [name, setName] = useState("feedback-privado-v1");
  const [seed, setSeed] = useState("local-ai-lab-split-2026");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const build = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await buildApprovedFeedbackDataset(name, seed);
      onCreated(record);
      setMessage(`Dataset inmutable creado con ${String(record.summary.included)} ejemplo(s); los candidatos se marcaron como exportados.`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "No se pudo construir el dataset.");
    } finally { setBusy(false); }
  };
  return <><div className="knowledge-controls dataset-controls"><label><span>Nombre de versión</span><input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} /></label><label><span>Semilla de split</span><input value={seed} onChange={(event) => setSeed(event.target.value)} disabled={busy} /></label><button onClick={() => void build()} disabled={busy || approvedCount === 0 || name.trim().length === 0 || seed.length < 8}>{busy ? "Construyendo…" : "Construir dataset aprobado"}</button><p>{approvedCount} candidato(s) con aprobación explícita. Los IDs y fingerprints de benchmark se excluyen automáticamente.</p></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}<RecordBoard records={records} emptyTitle="No hay datasets aprobados" emptyText="Revisa una respuesta, acéptala y aprueba por separado su uso para entrenamiento." /></>;
}

function OperationsBoard({ records, datasets, experiments, nodes, jobs, onChanged }: { records: ProductRecord[]; datasets: ProductRecord[]; experiments: ProductRecord[]; nodes: Overview["nodes"]; jobs: JobRecord[]; onChanged: () => void }) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [datasetId, setDatasetId] = useState(datasets[0]?.record_id ?? "");
  const [nodeId, setNodeId] = useState(nodes[0]?.node_id ?? "");
  const [baseModel, setBaseModel] = useState("");
  const [dtype, setDtype] = useState<"bf16" | "fp16">("bf16");
  const [preflightId, setPreflightId] = useState("");
  const [baselineId, setBaselineId] = useState(experiments[0]?.record_id ?? "");
  const [objective, setObjective] = useState("format");
  const [hypothesis, setHypothesis] = useState("");
  const [approvedBy, setApprovedBy] = useState("");
  const passedPreflights = records.filter((record) => record.status === "PREFLIGHT_PASSED");
  const successfulTraining = records.filter((record) => ["TRAINING_SUCCEEDED", "DISTILLATION_SUCCEEDED"].includes(record.status));
  const [trainingResultId, setTrainingResultId] = useState("");
  const [exportNodeId, setExportNodeId] = useState(nodes[0]?.node_id ?? "");
  const [exportFormats, setExportFormats] = useState<string[]>(["adapter"]);
  const [licenseId, setLicenseId] = useState("");
  const [servingRuntime, setServingRuntime] = useState("transformers");
  const [converterPath, setConverterPath] = useState("");
  const cancellable = new Set(["draft", "ready", "leased", "acknowledged", "running", "paused"]);
  const cancel = async (job: JobRecord) => {
    setBusyId(job.job_id); setMessage(null);
    try { const result = await cancelJob(job.job_id); setMessage(`Cancelación registrada: ${result.state}.`); onChanged(); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo cancelar el job."); }
    finally { setBusyId(null); }
  };
  const preflight = async () => {
    setBusyId("preflight"); setMessage(null);
    try {
      const created = await createTrainingPreflight({ datasetId, nodeId, baseModel, dtype, seed: 42, maxLength: 4096, rank: 8 });
      setMessage(`Preflight enviado al nodo ${nodeId}: ${created.record_id}.`); onChanged();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear el preflight."); }
    finally { setBusyId(null); }
  };
  const train = async () => {
    setBusyId("training"); setMessage(null);
    try {
      const created = await createTrainingRun({ datasetId, preflightJobId: preflightId, baselineExperimentId: baselineId, objective, hypothesis, approvedBy, epochs: 1 });
      setMessage(`Entrenamiento autorizado y enviado: ${created.record_id}.`); onChanged();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear el entrenamiento."); }
    finally { setBusyId(null); }
  };
  const toggleFormat = (format: string) => setExportFormats((current) => current.includes(format) ? current.filter((item) => item !== format) : [...current, format]);
  const exportModel = async () => {
    setBusyId("export"); setMessage(null);
    try {
      const created = await createModelExport({ trainingJobId: trainingResultId, nodeId: exportNodeId, formats: exportFormats, licenseId, servingRuntime, llamaCppConverter: converterPath });
      setMessage(`Exportación verificable enviada: ${created.record_id}.`); onChanged();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear la exportación."); }
    finally { setBusyId(null); }
  };
  return <><div className="operation-forms"><fieldset><legend>1 · Prueba corta obligatoria</legend><label><span>Dataset</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}><option value="">Selecciona</option>{datasets.map((item) => <option value={item.record_id} key={item.record_id}>{item.title}</option>)}</select></label><label><span>Nodo</span><select value={nodeId} onChange={(event) => setNodeId(event.target.value)}><option value="">Selecciona</option>{nodes.map((node) => <option value={node.node_id} key={node.node_id}>{node.hostname}</option>)}</select></label><label><span>Modelo local exacto</span><input value={baseModel} onChange={(event) => setBaseModel(event.target.value)} placeholder="ruta o ID presente en la caché del Worker" /></label><label><span>Dtype a probar</span><select value={dtype} onChange={(event) => setDtype(event.target.value as "bf16" | "fp16")}><option value="bf16">bf16</option><option value="fp16">fp16</option></select></label><button onClick={() => void preflight()} disabled={busyId !== null || !datasetId || !nodeId || !baseModel.trim()}>{busyId === "preflight" ? "Enviando…" : "Ejecutar C1–C6 + 8 ejemplos + resume"}</button></fieldset><fieldset><legend>2 · Entrenamiento largo autorizado</legend><label><span>Preflight aprobado</span><select value={preflightId} onChange={(event) => setPreflightId(event.target.value)}><option value="">Selecciona</option>{passedPreflights.map((item) => <option value={item.record_id} key={item.record_id}>{item.title} · {item.record_id.slice(0, 8)}</option>)}</select></label><label><span>Baseline</span><select value={baselineId} onChange={(event) => setBaselineId(event.target.value)}><option value="">Selecciona</option>{experiments.map((item) => <option value={item.record_id} key={item.record_id}>{item.title}</option>)}</select></label><label><span>Objetivo</span><select value={objective} onChange={(event) => setObjective(event.target.value)}><option value="format">Formato</option><option value="behavior">Comportamiento</option><option value="classification">Clasificación</option><option value="tool_selection">Selección de tools</option><option value="structured_arguments">Argumentos estructurados</option></select></label><label><span>Hipótesis falsable</span><textarea value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} /></label><label><span>Aprobado por</span><input value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} /></label><button onClick={() => void train()} disabled={busyId !== null || !datasetId || !preflightId || !baselineId || !hypothesis.trim() || !approvedBy.trim()}>{busyId === "training" ? "Enviando…" : "Autorizar entrenamiento"}</button></fieldset><fieldset><legend>3 · Exportación verificable</legend><label><span>Entrenamiento completado</span><select value={trainingResultId} onChange={(event) => setTrainingResultId(event.target.value)}><option value="">Selecciona</option>{successfulTraining.map((item) => <option value={item.record_id} key={item.record_id}>{item.title} · {item.record_id.slice(0, 8)}</option>)}</select></label><label><span>Nodo con conversión probada</span><select value={exportNodeId} onChange={(event) => setExportNodeId(event.target.value)}><option value="">Selecciona</option>{nodes.map((node) => <option value={node.node_id} key={node.node_id}>{node.hostname}</option>)}</select></label><div className="format-picker"><span>Formatos</span>{["adapter", "merged_model", "safetensors", "gguf"].map((format) => <label key={format}><input type="checkbox" checked={exportFormats.includes(format)} onChange={() => toggleFormat(format)} />{format}</label>)}</div><label><span>Licencia</span><input value={licenseId} onChange={(event) => setLicenseId(event.target.value)} placeholder="p. ej. apache-2.0" /></label><label><span>Runtime de serving</span><input value={servingRuntime} onChange={(event) => setServingRuntime(event.target.value)} /></label>{exportFormats.includes("gguf") ? <label><span>Conversor llama.cpp local</span><input value={converterPath} onChange={(event) => setConverterPath(event.target.value)} /></label> : null}<button onClick={() => void exportModel()} disabled={busyId !== null || !trainingResultId || !exportNodeId || exportFormats.length === 0 || !licenseId.trim() || !servingRuntime.trim() || (exportFormats.includes("gguf") && !converterPath.trim())}>{busyId === "export" ? "Enviando…" : "Crear paquete exportable"}</button><p>El Coordinator exige que cada formato figure como probado en el heartbeat del Worker.</p></fieldset></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}<RecordBoard records={records} emptyTitle="No hay operaciones autorizadas" emptyText="Ejecuta primero el preflight real; no se aceptan casillas declarativas como evidencia." /><section className="nodes-section"><h3>Jobs distribuidos</h3>{jobs.length ? <div className="table-wrap"><table><thead><tr><th>Trabajo</th><th>Estado</th><th>Nodo</th><th>Progreso</th><th>Control</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.job_id}><td><strong>{job.kind}</strong><code>{job.job_id}</code><small>correlation {job.correlation_id}</small></td><td><span className={`stamp ${recordStatus(job.state)}`}>{job.state}</span></td><td>{job.assigned_node_id ?? "sin asignar"}</td><td>{job.latest_progress ? JSON.stringify(job.latest_progress) : "—"}</td><td><button onClick={() => void cancel(job)} disabled={busyId !== null || !cancellable.has(job.state)}>{busyId === job.job_id ? "Cancelando…" : "Cancelar"}</button></td></tr>)}</tbody></table></div> : <p className="empty-row">No hay jobs enviados.</p>}</section></>;
}

function DistillationPanel({ datasets, preflights, experiments, onChanged }: { datasets: ProductRecord[]; preflights: ProductRecord[]; experiments: ProductRecord[]; onChanged: () => void }) {
  const missionDraft = useMemo(readMissionDraft, []);
  const brokerChecks = useMemo(
    () => experiments.filter((record) => record.status === "CAPABILITIES_SATISFIED" && record.summary.phase === "retrieval"),
    [experiments],
  );
  const [datasetId, setDatasetId] = useState(datasets[0]?.record_id ?? "");
  const [preflightJobId, setPreflightJobId] = useState(preflights[0]?.record_id ?? "");
  const [baselineExperimentId, setBaselineExperimentId] = useState(experiments[0]?.record_id ?? "");
  const [teacherSource, setTeacherSource] = useState<"broker" | "local">(missionDraft.teacherSource ?? "broker");
  const [brokerCheckId, setBrokerCheckId] = useState(brokerChecks[0]?.record_id ?? "");
  const [teacherBrokerEndpoint, setTeacherBrokerEndpoint] = useState("http://127.0.0.1:8000");
  const [teacherProvider, setTeacherProvider] = useState("");
  const [teacherDeployment, setTeacherDeployment] = useState("");
  const [teacherModel, setTeacherModel] = useState(missionDraft.teacherModel ?? "");
  const [teacherFingerprint, setTeacherFingerprint] = useState("");
  const [studentModel, setStudentModel] = useState(missionDraft.studentModel ?? "");
  const [studentFingerprint, setStudentFingerprint] = useState("");
  const [teacherLicense, setTeacherLicense] = useState("");
  const [studentLicense, setStudentLicense] = useState("");
  const [teacherAllowed, setTeacherAllowed] = useState(false);
  const [studentAllowed, setStudentAllowed] = useState(false);
  const [objective, setObjective] = useState("behavior");
  const [hypothesis, setHypothesis] = useState(missionDraft.success ?? "");
  const [approvedBy, setApprovedBy] = useState("");
  const [temperature, setTemperature] = useState(0);
  const [maxNewTokens, setMaxNewTokens] = useState(512);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    const selectedCheck = brokerChecks.find((record) => record.record_id === brokerCheckId);
    const observedEndpoint = selectedCheck?.summary.endpoint;
    if (typeof observedEndpoint === "string" && observedEndpoint.trim()) {
      setTeacherBrokerEndpoint(observedEndpoint);
    }
  }, [brokerCheckId, brokerChecks]);
  const sha = /^[0-9a-f]{64}$/;
  const teacherReady = teacherSource === "broker"
    ? brokerCheckId && teacherBrokerEndpoint.trim() && teacherProvider.trim() && teacherDeployment.trim()
    : sha.test(teacherFingerprint);
  const valid = datasetId && preflightJobId && baselineExperimentId && teacherModel.trim() && studentModel.trim() && teacherModel.trim() !== studentModel.trim() && teacherReady && sha.test(studentFingerprint) && teacherLicense.trim() && studentLicense.trim() && teacherAllowed && studentAllowed && hypothesis.trim() && approvedBy.trim();
  const run = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await createDistillationRun({
        datasetId, preflightJobId, baselineExperimentId,
        teacherSource,
        brokerCheckId: teacherSource === "broker" ? brokerCheckId : undefined,
        teacherBrokerEndpoint: teacherSource === "broker" ? teacherBrokerEndpoint : undefined,
        teacherProvider: teacherSource === "broker" ? teacherProvider : undefined,
        teacherDeployment: teacherSource === "broker" ? teacherDeployment : undefined,
        teacherModel,
        teacherModelFingerprint: teacherSource === "local" ? teacherFingerprint : undefined,
        studentModel, studentModelFingerprint: studentFingerprint,
        teacherLicense, studentLicense,
        teacherOutputsTrainingAllowed: teacherAllowed,
        studentFinetuningAllowed: studentAllowed,
        objective, hypothesis, approvedBy, epochs: 1,
        temperature, maxNewTokens,
      });
      setMessage(`Destilación enviada: ${record.record_id}. ${teacherSource === "broker" ? "AI Broker generará la supervisión con el modelo exacto;" : "el profesor se cargará desde la caché;"} el alumno se entrenará localmente.`);
      onChanged();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear la destilación."); }
    finally { setBusy(false); }
  };
  return <section className="distillation-panel">
    <header><p className="context">Nueva estrategia de entrenamiento</p><h2>Destilación profesor → alumno</h2><p>El profesor puede ejecutarse mediante AI Broker o desde la caché del Worker. El alumno y el adapter LoRA permanecen siempre en el entorno local.</p></header>
    <div className="capability-note"><strong>¿Qué es PEFT?</strong><span>Es la librería local que permite entrenar un adapter LoRA modificando una parte pequeña del alumno. No es otro modelo ni un servicio: la comprueba el preflight del Worker.</span></div>
    <div className="operation-forms"><fieldset><legend>1 · Evidencia y modelos</legend>
      <label><span>Dataset aprobado</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}><option value="">Selecciona</option>{datasets.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label>
      <label><span>Preflight del modelo alumno</span><select value={preflightJobId} onChange={(event) => setPreflightJobId(event.target.value)}><option value="">Selecciona</option>{preflights.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label>
      <label><span>Baseline comparable</span><select value={baselineExperimentId} onChange={(event) => setBaselineExperimentId(event.target.value)}><option value="">Selecciona</option>{experiments.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label>
      <label><span>Dónde está el profesor</span><select value={teacherSource} onChange={(event) => setTeacherSource(event.target.value as "broker" | "local")}><option value="broker">AI Broker</option><option value="local">Caché local del Worker</option></select></label>
      {teacherSource === "broker" ? <>
        <label><span>Comprobación compatible de AI Broker</span><select value={brokerCheckId} onChange={(event) => setBrokerCheckId(event.target.value)}><option value="">Selecciona</option>{brokerChecks.map((item) => <option key={item.record_id} value={item.record_id}>{item.title} · {String(item.summary.observed_contract)}</option>)}</select></label>
        <label><span>Endpoint comprobado de AI Broker</span><input value={teacherBrokerEndpoint} readOnly /></label>
        <label><span>Proveedor exacto</span><input value={teacherProvider} onChange={(event) => setTeacherProvider(event.target.value)} placeholder="p. ej. local" /></label>
        <label><span>Deployment exacto</span><input value={teacherDeployment} onChange={(event) => setTeacherDeployment(event.target.value)} placeholder="nombre anunciado por el Broker" /></label>
      </> : <label><span>SHA-256 del profesor local</span><input value={teacherFingerprint} onChange={(event) => setTeacherFingerprint(event.target.value.toLowerCase())} maxLength={64} /></label>}
      <label><span>Modelo profesor exacto</span><input value={teacherModel} onChange={(event) => setTeacherModel(event.target.value)} placeholder={teacherSource === "broker" ? "modelo anunciado por AI Broker" : "ruta o ID presente en caché"} /></label>
      <label><span>Modelo alumno local</span><input value={studentModel} onChange={(event) => setStudentModel(event.target.value)} placeholder="debe coincidir con el preflight" /></label>
      <label><span>SHA-256 del alumno</span><input value={studentFingerprint} onChange={(event) => setStudentFingerprint(event.target.value.toLowerCase())} maxLength={64} /></label>
    </fieldset><fieldset><legend>2 · Permisos de uso y autorización</legend>
      <p>No tienen que compartir la misma licencia. Debes confirmar que los términos de cada pieza permiten esta cadena concreta de uso.</p>
      <label><span>Licencia o términos del profesor</span><input value={teacherLicense} onChange={(event) => setTeacherLicense(event.target.value)} placeholder="nombre o referencia de los términos revisados" /></label>
      <label className="confirmation"><input type="checkbox" checked={teacherAllowed} onChange={(event) => setTeacherAllowed(event.target.checked)} /><span>He verificado que se pueden usar las respuestas del profesor como datos para entrenar otro modelo.</span></label>
      <label><span>Licencia o términos del alumno</span><input value={studentLicense} onChange={(event) => setStudentLicense(event.target.value)} /></label>
      <label className="confirmation"><input type="checkbox" checked={studentAllowed} onChange={(event) => setStudentAllowed(event.target.checked)} /><span>He verificado que el alumno permite fine-tuning y el uso previsto del adapter resultante.</span></label>
      <label><span>Objetivo</span><select value={objective} onChange={(event) => setObjective(event.target.value)}><option value="behavior">Comportamiento</option><option value="format">Formato</option><option value="classification">Clasificación</option><option value="procedure">Procedimiento</option><option value="tool_selection">Selección de tools</option></select></label>
      <label><span>Hipótesis falsable</span><textarea value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} /></label>
      <label><span>Aprobado por</span><input value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} /></label>
      <div className="distillation-generation"><label><span>Temperatura profesor</span><input type="number" min={0} max={2} step={0.1} value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></label><label><span>Máximo de tokens</span><input type="number" min={1} max={8192} value={maxNewTokens} onChange={(event) => setMaxNewTokens(Number(event.target.value))} /></label></div>
      <button onClick={() => void run()} disabled={busy || !valid}>{busy ? "Enviando…" : "Autorizar destilación"}</button>
    </fieldset></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}
  </section>;
}

function KnowledgeBoard({ records, onCreated }: { records: ProductRecord[]; onCreated: (record: ProductRecord) => void }) {
  const [root, setRoot] = useState("Y:\\Mi unidad\\Vaults");
  const [vaults, setVaults] = useState<string[]>([]);
  const [vault, setVault] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const snapshots = records.filter((record) => record.category === "snapshot" && record.status === "COMPLETE");
  const indexes = records.filter((record) => record.category === "index");
  const act = async (operation: () => Promise<void>) => {
    setBusy(true); setMessage(null);
    try { await operation(); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo completar la operación."); }
    finally { setBusy(false); }
  };
  const discover = () => void act(async () => {
    const found = await discoverVaults(root);
    setVaults(found); setVault(found[0] ?? "");
    setMessage(found.length ? `${found.length} vault(s) disponible(s).` : "No se encontraron vaults hijos en esa raíz.");
  });
  const snapshot = () => void act(async () => {
    const created = await createVaultSnapshot(root, vault);
    onCreated(created); setSnapshotId(created.record_id);
    setMessage(created.status === "COMPLETE" ? "Snapshot verificado. El vault no se modificó." : "El snapshot no convergió y quedó marcado INCOMPLETE.");
  });
  const index = () => void act(async () => {
    const previous = indexes[0]?.record_id;
    const created = await createKnowledgeIndex(snapshotId, previous);
    onCreated(created); setMessage(previous ? "Nueva generación incremental del índice creada." : "Índice local creado.");
  });
  return <><div className="knowledge-controls"><label><span>Raíz permitida de vaults</span><input value={root} onChange={(event) => setRoot(event.target.value)} disabled={busy} /></label><button onClick={discover} disabled={busy || !root.trim()}>Buscar vaults</button><label><span>Vault</span><select value={vault} onChange={(event) => setVault(event.target.value)} disabled={busy || !vaults.length}><option value="">Selecciona un vault</option>{vaults.map((name) => <option value={name} key={name}>{name}</option>)}</select></label><button onClick={snapshot} disabled={busy || !vault}>Crear snapshot read-only</button><label><span>Snapshot completo</span><select value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} disabled={busy || !snapshots.length}><option value="">Selecciona un snapshot</option>{snapshots.map((item) => <option value={item.record_id} key={item.record_id}>{item.title} · {item.artifact_sha256.slice(0, 8)}</option>)}</select></label><button onClick={index} disabled={busy || !snapshotId}>Construir índice</button></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}<RecordBoard records={records} emptyTitle="Todavía no hay snapshots registrados" emptyText="El snapshot se crea en almacenamiento local separado. La aplicación no expone operaciones de escritura sobre el vault." /></>;
}

function ReviewBoard({ reviews, onChanged }: { reviews: ReviewRecord[]; onChanged: (review: ReviewRecord) => void }) {
  const [selectedId, setSelectedId] = useState(reviews[0]?.review_id ?? "");
  const selected = reviews.find((item) => item.review_id === selectedId) ?? reviews[0];
  const [editor, setEditor] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (selected) setEditor(JSON.stringify(selected.corrected ?? selected.original, null, 2));
  }, [selected?.review_id, selected?.updated_at]);
  if (!reviews.length) return <div className="review-empty"><div className="review-example"><span>Original</span><p>La respuesta aparecerá aquí cuando exista una ejecución real.</p></div><div className="review-arrow" aria-hidden="true">→</div><div className="review-example corrected"><span>Corrección con evidencia</span><p>Ningún candidato pasa a training sin una revisión aceptada y otra aprobación explícita.</p></div></div>;
  if (!selected) return null;
  const perform = async (operation: () => Promise<ReviewRecord>, success: string) => {
    setBusy(true); setMessage(null);
    try { const changed = await operation(); onChanged(changed); setMessage(success); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo completar la operación."); }
    finally { setBusy(false); }
  };
  const save = () => {
    try {
      const parsed: unknown = JSON.parse(editor);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("La corrección debe ser un objeto JSON.");
      void perform(() => saveReviewCorrection(selected.review_id, parsed as Record<string, unknown>), "Corrección guardada y verificada.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "JSON no válido."); }
  };
  return <div className="review-workbench"><aside className="review-queue" aria-label="Cola de revisiones">{reviews.map((review) => <button key={review.review_id} className={review.review_id === selected.review_id ? "active" : ""} onClick={() => setSelectedId(review.review_id)}><strong>{review.case_id}</strong><span>{review.status} · training {review.training_state}</span></button>)}</aside><div className="review-editor"><div className="review-meta"><span className={`stamp ${recordStatus(selected.status)}`}>{selected.status}</span><span className={`stamp ${recordStatus(selected.training_state)}`}>training {selected.training_state}</span><code>{selected.snapshot_id}</code></div><div className="review-columns"><label><span>Respuesta original</span><pre>{JSON.stringify(selected.original, null, 2)}</pre></label><label><span>Corrección</span><textarea value={editor} onChange={(event) => setEditor(event.target.value)} spellCheck={false} disabled={busy || selected.status === "accepted"} /></label></div><div className="review-verification"><strong>{selected.verification?.deterministic_pass ? "Evidencia verificada" : "Pendiente de verificación"}</strong><span>{selected.diff_text ? "El diff está registrado y es recuperable." : "Guarda la corrección para generar el diff."}</span></div>{message ? <p className="review-message" role="status">{message}</p> : null}<div className="review-actions"><button onClick={save} disabled={busy || selected.status === "accepted"}>Guardar y verificar</button><button onClick={() => void perform(() => changeReviewState(selected.review_id, "submitted"), "Enviada a aprobación.")} disabled={busy || selected.status !== "draft" || !selected.verification?.deterministic_pass}>Enviar revisión</button><button onClick={() => void perform(() => changeReviewState(selected.review_id, "accepted"), "Revisión aceptada.")} disabled={busy || selected.status !== "submitted"}>Aceptar revisión</button><button onClick={() => void perform(() => changeTrainingState(selected.review_id, "proposed"), "Candidato propuesto; todavía no está aprobado.")} disabled={busy || selected.status !== "accepted" || selected.training_state !== "excluded"}>Proponer para training</button><button onClick={() => void perform(() => changeTrainingState(selected.review_id, "approved"), "Candidato aprobado explícitamente.")} disabled={busy || selected.training_state !== "proposed"}>Aprobar training</button></div></div></div>;
}

function summaryRows(summary: Record<string, unknown>): [string, string][] {
  return Object.entries(summary).slice(0, 6).map(([key, value]) => [key, typeof value === "object" ? JSON.stringify(value) : String(value)]);
}
function humanize(value: string) { return value.replaceAll("_", " "); }
function formatMetric(value: unknown) { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "—"; }
function recordStatus(value: string): EvidenceStatus { const folded = value.toLowerCase(); return folded.includes("block") || folded.includes("reject") || folded.includes("incomplete") ? "blocked" : folded.includes("complete") || folded.includes("approved") || folded.includes("verified") ? "tested" : folded.includes("pending") || folded.includes("draft") ? "pending" : "detected"; }

function GateState({ status }: { status?: string }) {
  const open = status === "open";
  return <div className={`gate-state ${open ? "open" : "closed"}`}><span aria-hidden="true" /><div><strong>{open ? "Puerta abierta" : "Puerta pendiente"}</strong><small>{status ?? "Coordinator no observado"}</small></div></div>;
}

function LoadingState() { return <div className="state-panel" role="status"><strong>Iniciando el Coordinator local…</strong><p>La vista aparecerá cuando el sidecar responda con un contrato válido.</p></div>; }
function EmptyState() { return <div className="state-panel"><strong>Sin evidencia disponible</strong><p>Registra un nodo o ejecuta un probe para empezar.</p></div>; }
function ErrorState({ message, retry }: { message: string; retry: () => void }) { return <div className="state-panel error" role="alert"><strong>No se pudo abrir la mesa de evidencia</strong><p>{message}</p><button onClick={retry}>Reintentar conexión</button></div>; }
function StaleState({ message, retry }: { message: string; retry: () => void }) { return <div className="stale-banner" role="status"><div><strong>Mostrando la última evidencia recibida</strong><span>{message}</span></div><button onClick={retry}>Volver a intentar</button></div>; }
function statusLabel(status: EvidenceStatus) { return ({ tested: "PROBADO", detected: "DETECTADO", pending: "PENDIENTE", blocked: "BLOQUEADO" } as const)[status]; }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "medium" }).format(date); }
