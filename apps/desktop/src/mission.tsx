/* La mision: estrategia elegida, borrador guardado y ruta completa. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  CheckCircle2,
  Database,
  FileSearch,
  FlaskConical,
  Network,
  PackageCheck,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
  type LucideIcon,
} from "lucide-react";

import { linkMissionEvidence, loadMissions, saveMission, unlinkMissionEvidence } from "./api";
import type { JobRecord, MissionRecord, MissionStrategy, Overview, ProductWorkspace, ReviewRecord } from "./contracts";

import { formatTime } from "./states";
import { missionFields, missionStorage, resolveMissionSelection, readMissionDraft, removeMissionDraft, sameMissionFields, writeMissionDraft, type MissionFields } from "./missionDraft";

export function MissionList({ missions, onOpen }: { missions: MissionRecord[]; onOpen: (id: string) => void }) {
  if (!missions.length) return <p>Aún no hay misiones guardadas. Crea una desde Misiones.</p>;
  return <div className="mission-saved-list">{missions.map((plan) => <button key={plan.mission_id} onClick={() => onOpen(plan.mission_id)}><strong>{plan.task}</strong><span>{missionStrategies.find((item) => item.id === plan.strategy)?.title ?? "Estrategia pendiente"}</span><small>{formatTime(plan.updated_at)} · Siguiente paso con evidencia pendiente: {plan.resume_step + 1}</small></button>)}</div>;
}

export const missionStrategies: { id: MissionStrategy; title: string; badge: string; description: string; icon: LucideIcon }[] = [
  { id: "recommend", title: "Comparar y elegir", badge: "Empezar aquí", description: "Mide alternativas simples con los mismos casos y elige con evidencia.", icon: Sparkles },
  { id: "prompting", title: "Prompting sin entrenamiento", badge: "Sin entrenamiento", description: "Prueba B0 y B1 con un modelo local antes de crear datasets o adaptadores.", icon: Target },
  { id: "rag", title: "RAG sin entrenamiento", badge: "Sin entrenamiento", description: "Responde con conocimiento de un snapshot y compara recuperación y respuesta.", icon: FileSearch },
  { id: "lora", title: "LoRA / SFT local", badge: "Disponible", description: "Especializa un modelo local con ejemplos aprobados y un adapter recuperable.", icon: Database },
  { id: "distillation", title: "Destilación de otro LLM", badge: "Disponible", description: "Un modelo profesor genera respuestas supervisadas para entrenar un modelo alumno más pequeño.", icon: Network },
];

export const missionStepIcons: LucideIcon[] = [Target, Users, Database, ShieldCheck, FlaskConical, BarChart3, PackageCheck];

export const missionFlows: Record<MissionStrategy, { title: string; input: string; output: string; destination?: string }[]> = {
  prompting: [
    { title: "Definir tarea", input: "Pregunta y criterio", output: "Objetivo medible" },
    { title: "Preparar casos", input: "Preguntas representativas", output: "Suite comparable", destination: "Experimentos" },
    { title: "Ejecutar B0 y B1", input: "Modelo local probado", output: "Respuestas y medidas", destination: "Experimentos" },
    { title: "Revisar respuestas", input: "Evidencias obtenidas", output: "Evaluación humana", destination: "Revisiones" },
    { title: "Elegir", input: "Calidad y coste", output: "Decisión explicada", destination: "Experimentos" },
  ],
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
    { title: "Preparar casos", input: "Preguntas y referencias", output: "Benchmark aprobado", destination: "Experimentos" },
    { title: "Evaluar con RAG", input: "Modelo e índice", output: "Comparación B0/R1–R4", destination: "Experimentos" },
    { title: "Revisar respuestas", input: "Citas y contexto", output: "Resultado revisado", destination: "Revisiones" },
    { title: "Elegir", input: "Calidad, tiempo y coste", output: "Estrategia seleccionada", destination: "Experimentos" },
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

const stageCategories: Record<MissionStrategy, string[][]> = {
  prompting: [[], ["benchmark"], ["experiment"], ["review"], ["experiment", "comparison"]],
  rag: [[], ["snapshot", "index"], ["benchmark"], ["experiment"], ["review"], ["experiment", "comparison"]],
  lora: [[], ["dataset"], ["training"], ["training"], ["experiment", "comparison"], ["export"]],
  distillation: [[], [], ["dataset"], ["training"], ["training"], ["experiment", "comparison"], ["export"]],
  recommend: [[], ["benchmark"], ["experiment"], ["review"], ["experiment", "comparison"]],
};

const stageLabels = {
  not_started: "Sin evidencia", configured: "Configurado", executed: "Ejecutado",
  validated: "Validado", attention: "Requiere atención",
};

function relevantTrainingEvidence(strategy: MissionStrategy, stage: number, status: string, kind: string): boolean {
  if (strategy === "lora" && stage === 2 || strategy === "distillation" && stage === 3) {
    return status.startsWith("PREFLIGHT_") || kind === "training.preflight.v1";
  }
  if (strategy === "lora" && stage === 3) return status.startsWith("TRAINING_") || kind === "training.lora.v1";
  if (strategy === "distillation" && stage === 4) return status.startsWith("DISTILLATION_") || kind === "training.distillation.v1";
  return true;
}

export function MissionBoard({ overview, product, reviews, jobs, missions, onChanged, onNavigate, registerExitGuard, selectedMissionId, onSelectMission }: {
  overview: Overview; product: ProductWorkspace | null; reviews: ReviewRecord[]; jobs: JobRecord[];
  missions: MissionRecord[]; onChanged: (mission: MissionRecord) => void; onNavigate: (page: string) => void;
  registerExitGuard: (guard: (() => boolean) | null) => void;
  selectedMissionId: string | null; onSelectMission: (id: string | null) => void;
}) {
  const [recovered] = useState(() => readMissionDraft(missionStorage(), selectedMissionId));
  const [strategy, setStrategy] = useState<MissionStrategy>(recovered?.fields.strategy ?? "recommend");
  const [activeStep, setActiveStep] = useState(0);
  const [mission, setMission] = useState<MissionRecord | null>(null);
  const [task, setTask] = useState(recovered?.fields.task ?? "");
  const [success, setSuccess] = useState(recovered?.fields.success ?? "");
  const [constraints, setConstraints] = useState(recovered?.fields.constraints ?? "");
  const [teacherSource, setTeacherSource] = useState<"broker" | "local">(recovered?.fields.teacherSource ?? "broker");
  const [teacherModel, setTeacherModel] = useState(recovered?.fields.teacherModel ?? "");
  const [studentModel, setStudentModel] = useState(recovered?.fields.studentModel ?? "");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [evidenceChoice, setEvidenceChoice] = useState("");
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [localSaved, setLocalSaved] = useState(true);
  const loadedId = useRef<string | null>(recovered?.missionId ?? null);
  const savedRevision = useRef(recovered?.expectedRevision ?? 0);
  const savedFields = useRef<MissionFields | null>(recovered?.base ?? null);
  const saveQueue = useRef<Promise<MissionRecord | undefined>>(Promise.resolve(undefined));
  const selection = resolveMissionSelection(selectedMissionId, missions);
  const missionId = selection.missing ? null : mission?.mission_id ?? loadedId.current ?? selection.missionId;
  const fields = useMemo(() => ({ strategy, task, success, constraints, teacherSource, teacherModel, studentModel }),
    [strategy, task, success, constraints, teacherSource, teacherModel, studentModel]);
  const latestFields = useRef(fields);
  latestFields.current = fields;
  const dirty = !sameMissionFields(fields, savedFields.current)
    && Boolean(missionId || task || success || constraints || teacherModel || studentModel);
  const flow = missionFlows[strategy];
  const current = flow[activeStep] ?? flow[0];

  const loadPlan = useCallback((plan: MissionRecord, discardLocal = false) => {
    const stored = discardLocal ? null : readMissionDraft(missionStorage(), plan.mission_id);
    const recovery = stored && !sameMissionFields(stored.fields, stored.base) ? stored : null;
    const next = recovery?.fields ?? missionFields(plan);
    savedRevision.current = recovery?.expectedRevision ?? plan.revision;
    savedFields.current = recovery?.base ?? missionFields(plan);
    loadedId.current = plan.mission_id;
    onSelectMission(plan.mission_id);
    setMission(plan); setStrategy(next.strategy); setTask(next.task); setSuccess(next.success);
    setConstraints(next.constraints); setTeacherSource(next.teacherSource);
    setTeacherModel(next.teacherModel); setStudentModel(next.studentModel);
    setConflict(Boolean(recovery && recovery.expectedRevision !== plan.revision));
    setActiveStep(plan.resume_step); setSavedAt(plan.updated_at);
    setEvidenceChoice(""); setMessage(null);
  }, [onSelectMission]);

  useEffect(() => {
    const found = missions.find((item) => item.mission_id === selectedMissionId);
    if (!found) return;
    if (loadedId.current !== found.mission_id || mission === null) loadPlan(found);
    else if (found.revision >= savedRevision.current) {
      setMission(found);
      if (found.revision !== savedRevision.current) {
        if (dirty || saving) setConflict(true);
        else loadPlan(found, true);
      }
    }
  }, [missions, loadPlan, dirty, saving, selectedMissionId, mission]);

  useEffect(() => {
    if (missionId && !mission) return;
    setLocalSaved(writeMissionDraft(missionStorage(), {
      missionId: selection.missing ? selectedMissionId : missionId,
      expectedRevision: savedRevision.current, fields, base: savedFields.current,
    }));
  }, [missionId, fields, savedAt, mission, selection.missing, selectedMissionId]);

  const canLeave = useCallback(() => {
    if (busy || saving) { setMessage("Espera a que termine el guardado antes de cambiar de pantalla."); return false; }
    return !dirty || localSaved || window.confirm("No se pudo conservar el borrador en este equipo. ¿Descartar los cambios y salir?");
  }, [busy, saving, dirty, localSaved]);
  useEffect(() => { registerExitGuard(canLeave); return () => registerExitGuard(null); }, [registerExitGuard, canLeave]);
  useEffect(() => {
    if (!dirty || localSaved) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, localSaved]);

  const persist = useCallback((): Promise<MissionRecord | undefined> => {
    if (!missionId) return Promise.resolve(undefined);
    if (conflict) return Promise.reject(new Error("La misión cambió en otra sesión. Tu borrador se conserva; revisa la versión guardada o crea una copia."));
    if (!task.trim() || !success.trim()) return Promise.reject(new Error("Completa la tarea y el criterio de éxito para guardar el plan."));
    const input = { missionId, strategy, task, success, constraints,
      teacherSource: strategy === "distillation" ? teacherSource : undefined,
      teacherModel: strategy === "distillation" ? teacherModel : undefined,
      studentModel: strategy === "distillation" ? studentModel : undefined };
    const operation = saveQueue.current.catch(() => undefined).then(async () => {
      if (sameMissionFields(fields, savedFields.current)) return mission ?? undefined;
      setSaving(true);
      try {
        const saved = await saveMission({ ...input, expectedRevision: savedRevision.current });
        savedRevision.current = saved.revision; savedFields.current = missionFields(saved);
        writeMissionDraft(missionStorage(), { missionId, expectedRevision: saved.revision,
          fields: latestFields.current, base: savedFields.current });
        setMission(saved); setSavedAt(saved.updated_at); setMessage(null); onChanged(saved);
        return saved;
      } catch (error) {
        if (String(error).includes("(409)")) setConflict(true);
        throw new Error(String(error).includes("(409)")
          ? "La misión cambió en otra sesión. Tu borrador local se conserva."
          : "No se pudo guardar en Coordinator. Tu borrador local se conserva; reintenta cuando vuelva la conexión.");
      } finally { setSaving(false); }
    });
    saveQueue.current = operation;
    return operation;
  }, [missionId, strategy, task, success, constraints, teacherSource, teacherModel, studentModel, onChanged, conflict, fields, mission]);

  useEffect(() => {
    if (!missionId || !dirty || conflict) return;
    const handle = window.setTimeout(() => { void persist().catch((reason) =>
      setMessage(reason instanceof Error ? reason.message : "No se pudo guardar la misión.")); }, 700);
    return () => window.clearTimeout(handle);
  }, [missionId, persist, dirty, conflict]);

  const createPlan = async () => {
    if (!task.trim() || !success.trim()) { setMessage("Describe la tarea y un criterio de éxito antes de crear el plan."); return; }
    setBusy(true); setMessage(null);
    try {
      const saved = await saveMission({ missionId: crypto.randomUUID(), strategy, task, success, constraints,
        teacherSource: strategy === "distillation" ? teacherSource : undefined,
        teacherModel: strategy === "distillation" ? teacherModel : undefined,
        studentModel: strategy === "distillation" ? studentModel : undefined });
      loadedId.current = saved.mission_id;
      savedRevision.current = saved.revision; savedFields.current = missionFields(saved);
      setConflict(false);
      if (!selectedMissionId) removeMissionDraft(missionStorage(), null);
      onSelectMission(saved.mission_id);
      setMission(saved); setSavedAt(saved.updated_at); setActiveStep(saved.resume_step);
      onChanged(saved);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear la misión."); }
    finally { setBusy(false); }
  };

  const startNewMission = async () => {
    if (!missionId && dirty && !window.confirm("¿Descartar este borrador y comenzar una misión nueva?")) return;
    try { await persist(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo guardar el borrador."); return; }
    const recovery = missionId || selection.missing ? readMissionDraft(missionStorage(), null) : null;
    loadedId.current = null; onSelectMission(null);
    savedRevision.current = 0; savedFields.current = null; setConflict(false);
    setMission(null); setStrategy(recovery?.fields.strategy ?? "recommend");
    setTask(recovery?.fields.task ?? ""); setSuccess(recovery?.fields.success ?? "");
    setConstraints(recovery?.fields.constraints ?? ""); setTeacherSource(recovery?.fields.teacherSource ?? "broker");
    setTeacherModel(recovery?.fields.teacherModel ?? ""); setStudentModel(recovery?.fields.studentModel ?? "");
    setActiveStep(0); setSavedAt(null); setMessage(recovery ? "Borrador anterior recuperado de este equipo." : null);
  };

  const chooseStrategy = async (next: MissionStrategy) => {
    if (strategy === next) return;
    const otherDraft = missionId || selection.missing ? readMissionDraft(missionStorage(), null) : null;
    if (otherDraft && [otherDraft.fields.task, otherDraft.fields.success, otherDraft.fields.constraints,
      otherDraft.fields.teacherModel, otherDraft.fields.studentModel].some((text) => text.trim())
      && !window.confirm("Hay otro borrador nuevo guardado en este equipo. ¿Sustituirlo con esta misión y la estrategia elegida?")) return;
    try { await persist(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo guardar el borrador."); return; }
    loadedId.current = null; onSelectMission(null);
    savedRevision.current = 0; savedFields.current = null; setConflict(false);
    setMission(null); setStrategy(next); setActiveStep(0); setSavedAt(null);
  };

  const selectPlan = async (id: string) => {
    try { await persist(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo guardar el borrador."); return; }
    const found = missions.find((item) => item.mission_id === id);
    if (found) loadPlan(found);
  };

  const continueFlow = async () => {
    try { await persist(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo guardar el borrador."); return; }
    if (current.destination) onNavigate(current.destination);
    else { setEvidenceChoice(""); setActiveStep((value) => Math.min(flow.length - 1, value + 1)); }
  };

  const candidates = useMemo(() => {
    const allowed = stageCategories[strategy][activeStep] ?? [];
    const records = product ? [...product.knowledge, ...product.benchmarks, ...product.experiments,
      ...product.datasets, ...product.training, ...product.exports] : [];
    const products = records.filter((item) => allowed.includes(item.category) &&
      relevantTrainingEvidence(strategy, activeStep, item.status, String(item.summary.kind ?? "")))
      .map((item) => ({ key: `product|${item.record_id}`, label: `${item.title} · ${item.status}` }));
    const reviewed = allowed.includes("review") ? reviews.map((item) => ({
      key: `review|${item.review_id}`, label: `${String(item.context.query ?? item.review_id)} · ${item.status}`,
    })) : [];
    const jobChoices = jobs.filter((item) => {
      const category = item.kind.startsWith("training.") ? "training" :
        item.kind.startsWith(("strategy.")) || item.kind.startsWith("experiment.") ? "experiment" :
        item.kind.startsWith("export.") || item.kind.startsWith("model.export.") ? "export" : "job";
      return allowed.includes(category) && relevantTrainingEvidence(strategy, activeStep, "", item.kind);
    }).map((item) => ({ key: `job|${item.job_id}`, label: `${item.kind} · ${item.state} · ${item.job_id.slice(0, 8)}` }));
    return [...products, ...reviewed, ...jobChoices];
  }, [strategy, activeStep, product, reviews, jobs]);

  const attachEvidence = async () => {
    if (!missionId || !evidenceChoice) return;
    const [referenceKind, referenceId] = evidenceChoice.split("|", 2);
    setBusy(true); setMessage(null);
    try {
      await persist();
      const changed = await linkMissionEvidence({ missionId, stageIndex: activeStep,
        referenceKind: referenceKind as "product" | "job" | "review", referenceId });
      setMission(changed); onChanged(changed); setEvidenceChoice("");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo vincular la evidencia."); }
    finally { setBusy(false); }
  };

  const detachEvidence = async (referenceKind: "product" | "job" | "review", referenceId: string) => {
    if (!missionId) return;
    setBusy(true); setMessage(null);
    try {
      const changed = await unlinkMissionEvidence({ missionId, stageIndex: activeStep,
        referenceKind, referenceId });
      setMission(changed); onChanged(changed);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo retirar la evidencia."); }
    finally { setBusy(false); }
  };

  const blockers = [
    strategy === "distillation" && !teacherModel.trim() ? "Falta elegir el modelo profesor" : null,
    strategy === "distillation" && !studentModel.trim() ? "Falta elegir el modelo alumno" : null,
    !overview.nodes.length && ["lora", "distillation"].includes(strategy) ? "Falta un Worker registrado" : null,
  ].filter((item): item is string => Boolean(item));
  const currentLinks = mission?.links.filter((item) => item.stage_index === activeStep) ?? [];

  return <section className="mission-board" aria-labelledby="mission-title">
    <header className="mission-heading"><div><p className="context">Misión actual</p><h1 id="mission-title">Quiero resolver una tarea</h1><p>Define qué necesitas y compara primero las opciones disponibles.</p></div>
      <div className="draft-state"><strong role="status">{saving ? "Guardando en Coordinator…" : conflict ? "Conflicto: borrador conservado" : dirty ? localSaved ? "Borrador guardado en este equipo" : "Borrador sin guardar" : savedAt ? "Plan guardado en Coordinator" : "Nuevo plan"}</strong><small>{savedAt ? formatTime(savedAt) : "Define tarea y criterio para guardarlo"}</small>
        {missions.length ? <select disabled={busy || saving} aria-label="Reanudar misión" value={missionId ?? ""} onChange={(event) => void selectPlan(event.target.value)}><option value="">Selecciona una misión</option>{missions.map((plan) => <option key={plan.mission_id} value={plan.mission_id}>{plan.task.slice(0, 60)}</option>)}</select> : null}
        <button disabled={busy || saving} onClick={() => void startNewMission()}>Nueva misión</button></div></header>
    <div className="strategy-start"><div><h2>¿Cómo quieres conseguirlo?</h2><div className="strategy-list">{missionStrategies.map((item) => { const Icon = item.icon; return <button key={item.id} disabled={busy || saving} className={strategy === item.id ? "selected" : ""} onClick={() => void chooseStrategy(item.id)} aria-pressed={strategy === item.id}><Icon aria-hidden="true" size={25} strokeWidth={1.7} /><span><strong>{item.title}</strong><small>{item.description}</small></span><b>{item.badge}</b></button>; })}</div>
      <button className="primary-action" onClick={() => void createPlan()} disabled={busy || Boolean(missionId) || !task.trim() || !success.trim()}>{missionId ? "Plan creado" : "Crear plan guiado"}</button></div>
      <div className="strategy-explainer"><strong>{missionStrategies.find((item) => item.id === strategy)?.title}</strong><p>{missionStrategies.find((item) => item.id === strategy)?.description}</p>{strategy === "distillation" ? <div className="capability-note"><strong>Destilación secuencial profesor → alumno disponible</strong><span>El profesor puede ejecutarse mediante AI Broker o desde la caché local. El alumno se entrena localmente con LoRA y se compara contra el baseline.</span></div> : null}</div></div>
    <ol className="mission-flow" aria-label="Recorrido con estado derivado de evidencia">{flow.map((step, index) => { const StepIcon = missionStepIcons[index] ?? CheckCircle2; const stageState = mission?.stage_states[index] ?? "not_started"; return <li key={step.title} className={`${index === activeStep ? "active" : ""} ${stageState}`}><button onClick={() => { if (missionId) { setActiveStep(index); setEvidenceChoice(""); } }} disabled={!missionId}><span><StepIcon aria-hidden="true" size={17} strokeWidth={1.8} /></span><strong>{index + 1}. {step.title}</strong><small>{stageLabels[stageState]}</small><small>Salida: {step.output}</small></button></li>; })}</ol>
    <div className="mission-workbench"><section className="step-workspace"><div className="step-title"><span>{(() => { const StepIcon = missionStepIcons[activeStep] ?? CheckCircle2; return <StepIcon aria-hidden="true" size={18} />; })()}</span><div><h2>{activeStep + 1} · {current.title}</h2><p>{activeStep === 0 ? "Define la tarea, su criterio de éxito y los límites." : `Resultado esperado: ${current.output}. El estado solo cambia cuando se vincula evidencia real.`}</p></div></div>
      {activeStep === 0 ? <div className="mission-fields"><label><span>Tarea a resolver</span><textarea disabled={busy} value={task} onChange={(event) => setTask(event.target.value)} placeholder="Describe la tarea concreta." /></label><label><span>Criterio de éxito</span><textarea disabled={busy} value={success} onChange={(event) => setSuccess(event.target.value)} placeholder="Indica una medida verificable frente al baseline." /></label><label><span>Restricciones</span><textarea disabled={busy} value={constraints} onChange={(event) => setConstraints(event.target.value)} placeholder="Datos excluidos, idiomas, latencia, permisos o privacidad." /></label></div> : strategy === "distillation" && activeStep === 1 ? <div className="mission-fields two-columns"><label><span>Dónde está el profesor</span><select disabled={busy} value={teacherSource} onChange={(event) => setTeacherSource(event.target.value as "broker" | "local")}><option value="broker">AI Broker</option><option value="local">Caché local del Worker</option></select></label><label><span>Modelo profesor exacto</span><input disabled={busy} value={teacherModel} onChange={(event) => setTeacherModel(event.target.value)} /></label><label><span>Modelo alumno local</span><input disabled={busy} value={studentModel} onChange={(event) => setStudentModel(event.target.value)} /></label></div> : <div className="step-guidance"><strong>Trabaja y vuelve con el resultado</strong><p>Abre la herramienta de esta etapa. Cuando produzca un resultado, regresa para vincularlo a esta misión.</p></div>}
      {missionId && stageCategories[strategy][activeStep]?.length ? <div className="mission-evidence"><strong>Evidencia de esta etapa</strong><div className="knowledge-controls"><select aria-label="Seleccionar evidencia" value={evidenceChoice} onChange={(event) => setEvidenceChoice(event.target.value)}><option value="">Selecciona un resultado o job</option>{candidates.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}</select><button onClick={() => void attachEvidence()} disabled={busy || saving || conflict || !evidenceChoice}>Vincular evidencia</button></div>{currentLinks.length ? <ul>{currentLinks.map((item) => <li key={`${item.reference_kind}-${item.reference_id}`}><span>{item.title} · {item.status} · {stageLabels[item.stage_state]}{item.reason ? <small>{item.reason}</small> : null}</span><button onClick={() => void detachEvidence(item.reference_kind, item.reference_id)} disabled={busy}>Retirar</button></li>)}</ul> : <p>Aún no hay evidencia vinculada a esta etapa.</p>}</div> : null}
      {selection.missing ? <p role="alert">La misión seleccionada ya no está en Coordinator. El texto recuperado se conserva: puedes crear un plan nuevo con él, abrir otra misión o recuperar el borrador nuevo anterior.</p> : null}
      {!localSaved ? <p role="alert">No se pudo conservar el borrador en este equipo. Guarda el plan antes de salir.</p> : null}
      {conflict ? <div role="alert"><p>La misión cambió en otra sesión. Tu texto local se conserva. Revisa la versión guardada o guarda tu trabajo como una misión nueva.</p><button disabled={busy || saving} onClick={() => void (async () => {
        if (!window.confirm("Se descartará este borrador para cargar la versión guardada. ¿Continuar?")) return;
        setBusy(true);
        try { const fresh = (await loadMissions()).find((item) => item.mission_id === missionId); if (!fresh) throw new Error("No se encontró la misión guardada."); loadPlan(fresh, true); }
        catch (error) { setMessage(String(error)); } finally { setBusy(false); }
      })()}>Cargar versión guardada</button><button disabled={busy || saving || !task.trim() || !success.trim()} onClick={() => void createPlan()}>Crear copia con mi borrador</button></div> : null}
      {message ? <p role="status" className="knowledge-message">{message}</p> : null}
      <footer><button className="secondary-action" onClick={() => void persist().catch((reason) => setMessage(reason instanceof Error ? reason.message : "No se pudo guardar."))} disabled={!missionId || busy || saving || conflict}>Guardar plan</button><button className="primary-action" disabled={!missionId || busy || saving || conflict || (activeStep === 0 && (!task.trim() || !success.trim()))} onClick={() => void continueFlow()}>{current.destination ? `Abrir ${current.destination}` : activeStep === flow.length - 1 ? "Revisar resultado" : "Continuar"}</button></footer></section>
      <aside className="plan-preview"><h2>Vista previa del plan</h2><dl><div><dt>Estrategia</dt><dd>{missionStrategies.find((item) => item.id === strategy)?.title}</dd></div>{strategy === "distillation" ? <><div><dt>Origen del profesor</dt><dd>{teacherSource === "broker" ? "AI Broker" : "Worker local"}</dd></div><div><dt>Modelo profesor</dt><dd>{teacherModel || "Sin definir"}</dd></div><div><dt>Modelo alumno</dt><dd>{studentModel || "Sin definir"}</dd></div></> : null}<div><dt>Datasets disponibles</dt><dd>{product?.datasets.length ?? 0}</dd></div><div><dt>Workers registrados</dt><dd>{overview.nodes.length}</dd></div><div><dt>Tratamiento de datos</dt><dd>Equipo local o red privada, según Worker y Broker elegidos</dd></div><div><dt>Bloqueadores detectados</dt><dd className={blockers.length ? "pending" : "tested"}>{blockers.length || "Ninguno"}</dd></div></dl>{blockers.length ? <ul>{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul> : null}<div className="expected-result"><strong>Resultado final esperado</strong><span>{strategy === "distillation" ? "Modelo alumno validado + informe comparativo + paquete exportable" : ["recommend", "prompting", "rag"].includes(strategy) ? "Respuestas revisadas + evidencia comparable + decisión explicada" : "Modelo validado + evidencia comparable + paquete exportable"}</span></div></aside></div>
  </section>;
}
