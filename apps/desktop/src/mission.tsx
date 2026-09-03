/* La mision: estrategia elegida, borrador guardado y ruta completa. */
import { useCallback, useEffect, useState } from "react";
import {
  BarChart3,
  Check,
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

import type { Overview, ProductWorkspace } from "./contracts";

import { formatTime } from "./states";

export type MissionStrategy = "lora" | "rag" | "distillation" | "recommend";
export type MissionDraft = Partial<{ strategy: MissionStrategy; task: string; success: string; constraints: string; teacherSource: "broker" | "local"; teacherModel: string; studentModel: string; created: boolean; activeStep: number; savedAt: string }>;

export function readMissionDraft(): MissionDraft {
  try {
    const raw = window.localStorage.getItem("local-ai-lab.mission-draft.v1");
    return raw ? JSON.parse(raw) as MissionDraft : {};
  } catch { return {}; }
}

export const missionStrategies: { id: MissionStrategy; title: string; badge: string; description: string; icon: LucideIcon }[] = [
  { id: "lora", title: "LoRA / SFT local", badge: "Disponible", description: "Especializa un modelo local con ejemplos aprobados y un adapter recuperable.", icon: Database },
  { id: "rag", title: "Fine-tuning + RAG", badge: "Disponible", description: "Combina comportamiento entrenado con conocimiento recuperado desde un snapshot.", icon: FileSearch },
  { id: "distillation", title: "Destilación de otro LLM", badge: "Disponible", description: "Un modelo profesor genera respuestas supervisadas para entrenar un modelo alumno más pequeño.", icon: Network },
  { id: "recommend", title: "Que la app recomiende", badge: "Compara alternativas", description: "Usa evidencia comparable para elegir la solución menos compleja que cumpla el objetivo.", icon: Sparkles },
];

export const missionStepIcons: LucideIcon[] = [Target, Users, Database, ShieldCheck, FlaskConical, BarChart3, PackageCheck];

export const missionFlows: Record<MissionStrategy, { title: string; input: string; output: string; destination?: string }[]> = {
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

export function MissionBoard({ overview, product, onNavigate }: { overview: Overview; product: ProductWorkspace | null; onNavigate: (page: string) => void }) {
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
    <div className="strategy-start"><div><h2>¿Cómo quieres conseguirlo?</h2><div className="strategy-list">{missionStrategies.map((item) => { const Icon = item.icon; return <button key={item.id} className={strategy === item.id ? "selected" : ""} onClick={() => chooseStrategy(item.id)} aria-pressed={strategy === item.id}><Icon aria-hidden="true" size={25} strokeWidth={1.7} /><span><strong>{item.title}</strong><small>{item.description}</small></span><b>{item.badge}</b></button>; })}</div><button className="primary-action" onClick={createPlan}>{created ? "Recrear plan guiado" : "Crear plan guiado"}</button></div><div className="strategy-explainer"><strong>{missionStrategies.find((item) => item.id === strategy)?.title}</strong><p>{missionStrategies.find((item) => item.id === strategy)?.description}</p>{strategy === "distillation" ? <div className="capability-note"><strong>Destilación secuencial profesor → alumno disponible</strong><span>El profesor puede ejecutarse mediante AI Broker o desde la caché local. El alumno siempre se entrena localmente con LoRA y después se compara contra el baseline.</span></div> : null}</div></div>
    <ol className="mission-flow" aria-label="Recorrido completo">{flow.map((step, index) => { const StepIcon = missionStepIcons[index] ?? CheckCircle2; return <li key={step.title} className={index === activeStep ? "active" : index < activeStep ? "complete" : ""}><button onClick={() => created && setActiveStep(index)} disabled={!created}><span>{index < activeStep ? <Check aria-label="Completado" size={17} /> : <StepIcon aria-hidden="true" size={17} strokeWidth={1.8} />}</span><strong>{index + 1}. {step.title}</strong><small>Entrada: {step.input}</small><small>Salida: {step.output}</small></button></li>; })}</ol>
    <div className="mission-workbench"><section className="step-workspace"><div className="step-title"><span>{(() => { const StepIcon = missionStepIcons[activeStep] ?? CheckCircle2; return <StepIcon aria-hidden="true" size={18} />; })()}</span><div><h2>{activeStep + 1} · {current.title}</h2><p>{activeStep === 0 ? "Define qué debe aprender el modelo, cómo sabrás que tuvo éxito y qué límites debe respetar." : `Completa esta etapa para producir: ${current.output}.`}</p></div></div>{activeStep === 0 ? <div className="mission-fields"><label><span>Tarea que debe aprender</span><textarea value={task} onChange={(event) => setTask(event.target.value)} placeholder="Describe la tarea o comportamiento que el modelo alumno debe dominar." /></label><label><span>Criterio de éxito</span><textarea value={success} onChange={(event) => setSuccess(event.target.value)} placeholder="Indica una medida verificable frente al baseline." /></label><label><span>Restricciones</span><textarea value={constraints} onChange={(event) => setConstraints(event.target.value)} placeholder="Datos excluidos, idiomas, latencia, permisos de uso o límites de privacidad." /></label></div> : strategy === "distillation" && activeStep === 1 ? <div className="mission-fields two-columns"><label><span>Dónde está el profesor</span><select value={teacherSource} onChange={(event) => setTeacherSource(event.target.value as "broker" | "local")}><option value="broker">AI Broker</option><option value="local">Caché local del Worker</option></select></label><label><span>{teacherSource === "broker" ? "Modelo profesor en AI Broker" : "Modelo profesor local"}</span><input value={teacherModel} onChange={(event) => setTeacherModel(event.target.value)} placeholder={teacherSource === "broker" ? "Nombre exacto anunciado por el Broker" : "Ruta o ID ya presente en caché"} /></label><label><span>Modelo alumno local</span><input value={studentModel} onChange={(event) => setStudentModel(event.target.value)} placeholder="Ruta o ID ya presente en caché" /></label></div> : <div className="step-guidance"><strong>Qué ocurrirá aquí</strong><p>La aplicación abrirá las herramientas necesarias con el contexto del plan y conservará la evidencia producida para poder reanudar el recorrido.</p></div>}<footer><button className="secondary-action" onClick={saveDraft}>Guardar borrador</button><button className="primary-action" disabled={!created || (activeStep === 0 && (!task.trim() || !success.trim()))} onClick={continueFlow}>{current.destination ? `Abrir ${current.destination}` : activeStep === flow.length - 1 ? "Revisar resultado" : "Continuar"}</button></footer></section>
      <aside className="plan-preview"><h2>Vista previa del plan</h2><dl><div><dt>Estrategia</dt><dd>{missionStrategies.find((item) => item.id === strategy)?.title}</dd></div>{strategy === "distillation" ? <><div><dt>Origen del profesor</dt><dd>{teacherSource === "broker" ? "AI Broker" : "Worker local"}</dd></div><div><dt>Modelo profesor</dt><dd>{teacherModel || "Sin definir"}</dd></div><div><dt>Modelo alumno</dt><dd>{studentModel || "Sin definir"}</dd></div></> : null}<div><dt>Datasets disponibles</dt><dd>{product?.datasets.length ?? 0}</dd></div><div><dt>Workers registrados</dt><dd>{overview.nodes.length}</dd></div><div><dt>Límite de privacidad</dt><dd>Solo este equipo</dd></div><div><dt>Bloqueadores detectados</dt><dd className={blockers.length ? "pending" : "tested"}>{blockers.length || "Ninguno"}</dd></div></dl>{blockers.length ? <ul>{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul> : null}<div className="expected-result"><strong>Resultado final esperado</strong><span>{strategy === "distillation" ? "Modelo alumno validado + informe comparativo + paquete exportable" : "Modelo validado + evidencia comparable + paquete exportable"}</span></div></aside></div>
  </section>;
}
