/* Datasets, operaciones de entrenamiento y destilacion. */
import { useEffect, useMemo, useState } from "react";

import {
  buildApprovedFeedbackDataset,
  cancelJob,
  createDistillationRun,
  createModelExport,
  createTrainingPreflight,
  createTrainingRun,
} from "./api";
import type { JobRecord, Overview, ProductRecord } from "./contracts";
import { recordStatus } from "./format";

import { RecordBoard } from "./overview";

import { readMissionDraft } from "./mission";
export function DatasetBoard({ records, approvedCount, onCreated }: { records: ProductRecord[]; approvedCount: number; onCreated: (record: ProductRecord) => void }) {
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

export function OperationsBoard({ records, datasets, experiments, nodes, jobs, onChanged }: { records: ProductRecord[]; datasets: ProductRecord[]; experiments: ProductRecord[]; nodes: Overview["nodes"]; jobs: JobRecord[]; onChanged: () => void }) {
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

export function DistillationPanel({ datasets, preflights, experiments, onChanged }: { datasets: ProductRecord[]; preflights: ProductRecord[]; experiments: ProductRecord[]; onChanged: () => void }) {
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
