/* Datasets, operaciones de entrenamiento y destilacion. */
import { useEffect, useMemo, useState } from "react";

import {
  buildApprovedFeedbackDataset,
  cancelJob,
  createDistillationRun,
  createTrainingPreflight,
  createTrainingRun,
} from "./api";
import type { JobRecord, MissionRecord, Overview, ProductRecord, ReviewRecord } from "./contracts";
import { recordStatus } from "./format";
import { useBrokerEndpoint } from "./brokerEndpoint";

import { RecordBoard } from "./overview";
import { ExportPanel } from "./ExportPanel";


function trainingBaselines(experiments: ProductRecord[], dataset: ProductRecord | undefined): ProductRecord[] {
  if (!dataset || dataset.status !== "READY_FOR_TRAINING") return [];
  return experiments.filter((record) =>
    record.status === "EXPERIMENT_SUCCEEDED" &&
    ["B1", "R4"].includes(String(record.summary.strategy_id)) &&
    record.summary.snapshot_id === dataset.summary.snapshot_id &&
    record.summary.snapshot_hash === dataset.summary.snapshot_hash &&
    typeof (record.summary.quality as { deterministic_pass_rate?: unknown } | undefined)?.deterministic_pass_rate === "number"
  );
}

export function DatasetBoard({ records, reviews, snapshots, onCreated }: { records: ProductRecord[]; reviews: ReviewRecord[]; snapshots: ProductRecord[]; onCreated: (record: ProductRecord) => void }) {
  const [name, setName] = useState("feedback-privado-v1");
  const [seed, setSeed] = useState("local-ai-lab-split-2026");
  const [sourceSnapshotId, setSourceSnapshotId] = useState("");
  const choices = snapshots.filter((item) => item.category === "snapshot" && item.status === "COMPLETE");
  useEffect(() => {
    if (!choices.some((item) => item.record_id === sourceSnapshotId)) setSourceSnapshotId(choices[0]?.record_id ?? "");
  }, [snapshots, sourceSnapshotId]);
  const approvedCount = reviews.filter((review) => review.training_state === "approved" && review.snapshot_id === sourceSnapshotId).length;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const build = async () => {
    setBusy(true); setMessage(null);
    try {
      const record = await buildApprovedFeedbackDataset(name, seed, sourceSnapshotId);
      onCreated(record);
      setMessage(`Dataset inmutable creado con ${String(record.summary.included)} ejemplo(s); los candidatos se marcaron como exportados.`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "No se pudo construir el dataset.");
    } finally { setBusy(false); }
  };
  return <><div className="knowledge-controls dataset-controls"><label><span>Snapshot de los ejemplos</span><select value={sourceSnapshotId} onChange={(event) => setSourceSnapshotId(event.target.value)} disabled={busy}><option value="">Selecciona</option>{choices.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label><label><span>Nombre de versión</span><input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} /></label><label><span>Semilla de split</span><input value={seed} onChange={(event) => setSeed(event.target.value)} disabled={busy} /></label><button onClick={() => void build()} disabled={busy || !sourceSnapshotId || approvedCount === 0 || name.trim().length === 0 || seed.length < 8}>{busy ? "Construyendo…" : "Construir dataset aprobado"}</button><p>{approvedCount} candidato(s) aprobados para este snapshot. Las preguntas de benchmark se excluyen automáticamente.</p></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}<RecordBoard records={records} emptyTitle="No hay datasets aprobados" emptyText="Revisa una respuesta, acéptala y aprueba por separado su uso para entrenamiento." /></>;
}

export function OperationsBoard({ records, datasets, experiments, nodes, jobs, onChanged }: { records: ProductRecord[]; datasets: ProductRecord[]; experiments: ProductRecord[]; nodes: Overview["nodes"]; jobs: JobRecord[]; onChanged: () => void }) {
  const [datasetId, setDatasetId] = useState(datasets[0]?.record_id ?? "");
  const eligibleBaselines = trainingBaselines(experiments, datasets.find((item) => item.record_id === datasetId));
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [nodeId, setNodeId] = useState(nodes[0]?.node_id ?? "");
  const [baseModel, setBaseModel] = useState("");
  const [dtype, setDtype] = useState<"bf16" | "fp16">("bf16");
  const [preflightId, setPreflightId] = useState("");
  const [baselineId, setBaselineId] = useState(eligibleBaselines[0]?.record_id ?? "");
  useEffect(() => {
    if (!eligibleBaselines.some((record) => record.record_id === baselineId)) setBaselineId(eligibleBaselines[0]?.record_id ?? "");
  }, [experiments, datasets, datasetId, baselineId]);
  const [objective, setObjective] = useState("format");
  const [hypothesis, setHypothesis] = useState("");
  const [approvedBy, setApprovedBy] = useState("");
  const [noMutableFactsConfirmed, setNoMutableFactsConfirmed] = useState(false);
  const [minimumQualityGain, setMinimumQualityGain] = useState(0.05);
  const passedPreflights = records.filter((record) => record.status === "PREFLIGHT_PASSED");
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
      const created = await createTrainingRun({ datasetId, preflightJobId: preflightId, baselineExperimentId: baselineId, objective, hypothesis, containsMutableFacts: false, minimumQualityGain, approvedBy, epochs: 1 });
      setMessage(`Entrenamiento autorizado y enviado: ${created.record_id}.`); onChanged();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo crear el entrenamiento."); }
    finally { setBusyId(null); }
  };
  return <><div className="operation-forms"><fieldset><legend>1 · Prueba corta obligatoria</legend><label><span>Dataset</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}><option value="">Selecciona</option>{datasets.map((item) => <option value={item.record_id} key={item.record_id}>{item.title}</option>)}</select></label><label><span>Nodo</span><select value={nodeId} onChange={(event) => setNodeId(event.target.value)}><option value="">Selecciona</option>{nodes.map((node) => <option value={node.node_id} key={node.node_id}>{node.hostname}</option>)}</select></label><label><span>Modelo local exacto</span><input value={baseModel} onChange={(event) => setBaseModel(event.target.value)} placeholder="ruta o ID presente en la caché del Worker" /></label><label><span>Dtype a probar</span><select value={dtype} onChange={(event) => setDtype(event.target.value as "bf16" | "fp16")}><option value="bf16">bf16</option><option value="fp16">fp16</option></select></label><button onClick={() => void preflight()} disabled={busyId !== null || !datasetId || !nodeId || !baseModel.trim()}>{busyId === "preflight" ? "Enviando…" : "Ejecutar C1–C6 + 8 ejemplos + resume"}</button></fieldset><fieldset><legend>2 · Entrenamiento largo autorizado</legend><label><span>Preflight aprobado</span><select value={preflightId} onChange={(event) => setPreflightId(event.target.value)}><option value="">Selecciona</option>{passedPreflights.map((item) => <option value={item.record_id} key={item.record_id}>{item.title} · {item.record_id.slice(0, 8)}</option>)}</select></label><label><span>Baseline comparable B1 o R4 completado</span><select value={baselineId} onChange={(event) => setBaselineId(event.target.value)}><option value="">Selecciona</option>{eligibleBaselines.map((item) => <option value={item.record_id} key={item.record_id}>{item.title}</option>)}</select></label><label><span>Objetivo</span><select value={objective} onChange={(event) => setObjective(event.target.value)}><option value="format">Formato</option><option value="behavior">Comportamiento</option><option value="classification">Clasificación</option><option value="tool_selection">Selección de tools</option><option value="structured_arguments">Argumentos estructurados</option></select></label><label><span>Hipótesis falsable</span><textarea value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} /></label><label><span>Aprobado por</span><input value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} /></label><label className="confirmation"><input type="checkbox" checked={noMutableFactsConfirmed} onChange={(event) => setNoMutableFactsConfirmed(event.target.checked)} /><span>Confirmo que este objetivo no memoriza hechos cambiantes del vault.</span></label><label><span>Mejora mínima de verificación de formato y citas (0–1)</span><input type="number" min={0.01} max={1} step={0.01} value={minimumQualityGain} onChange={(event) => setMinimumQualityGain(Number(event.target.value))} /></label><button onClick={() => void train()} disabled={busyId !== null || !datasetId || !preflightId || !baselineId || !hypothesis.trim() || !approvedBy.trim() || !noMutableFactsConfirmed || !Number.isFinite(minimumQualityGain) || minimumQualityGain <= 0 || minimumQualityGain > 1}>{busyId === "training" ? "Enviando…" : "Autorizar entrenamiento"}</button></fieldset><ExportPanel records={records} nodes={nodes} onChanged={onChanged} /></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}<RecordBoard records={records} emptyTitle="No hay operaciones autorizadas" emptyText="Ejecuta primero el preflight real; no se aceptan casillas declarativas como evidencia." /><section className="nodes-section"><h3>Jobs distribuidos</h3>{jobs.length ? <div className="table-wrap"><table><thead><tr><th>Trabajo</th><th>Estado</th><th>Nodo</th><th>Progreso</th><th>Control</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.job_id}><td><strong>{job.kind}</strong><code>{job.job_id}</code><small>correlation {job.correlation_id}</small></td><td><span className={`stamp ${recordStatus(job.state)}`}>{job.state}</span></td><td>{job.assigned_node_id ?? "sin asignar"}</td><td>{job.latest_progress ? JSON.stringify(job.latest_progress) : "—"}</td><td><button onClick={() => void cancel(job)} disabled={busyId !== null || !cancellable.has(job.state)}>{busyId === job.job_id ? "Cancelando…" : "Cancelar"}</button></td></tr>)}</tbody></table></div> : <p className="empty-row">No hay jobs enviados.</p>}</section></>;
}

export function DistillationPanel({ mission, datasets, preflights, experiments, onChanged }: { mission?: MissionRecord; datasets: ProductRecord[]; preflights: ProductRecord[]; experiments: ProductRecord[]; onChanged: () => void }) {
  const brokerChecks = useMemo(
    () => experiments.filter((record) => record.status === "CAPABILITIES_SATISFIED" && record.summary.phase === "retrieval"),
    [experiments],
  );
  const [datasetId, setDatasetId] = useState(datasets[0]?.record_id ?? "");
  const eligibleBaselines = trainingBaselines(experiments, datasets.find((item) => item.record_id === datasetId));
  const [preflightJobId, setPreflightJobId] = useState(preflights[0]?.record_id ?? "");
  const [baselineExperimentId, setBaselineExperimentId] = useState(eligibleBaselines[0]?.record_id ?? "");
  useEffect(() => {
    if (!eligibleBaselines.some((record) => record.record_id === baselineExperimentId)) setBaselineExperimentId(eligibleBaselines[0]?.record_id ?? "");
  }, [experiments, datasets, datasetId, baselineExperimentId]);
  const [teacherSource, setTeacherSource] = useState<"broker" | "local">(mission?.teacher_source ?? "broker");
  const [brokerCheckId, setBrokerCheckId] = useState(brokerChecks[0]?.record_id ?? "");
  const [configuredBrokerEndpoint] = useBrokerEndpoint();
  const [teacherBrokerEndpoint, setTeacherBrokerEndpoint] = useState(configuredBrokerEndpoint);
  const [teacherProvider, setTeacherProvider] = useState("");
  const [teacherDeployment, setTeacherDeployment] = useState("");
  const [teacherModel, setTeacherModel] = useState(mission?.teacher_model ?? "");
  const [teacherFingerprint, setTeacherFingerprint] = useState("");
  const [studentModel, setStudentModel] = useState(mission?.student_model ?? "");
  const [studentFingerprint, setStudentFingerprint] = useState("");
  const [teacherLicense, setTeacherLicense] = useState("");
  const [studentLicense, setStudentLicense] = useState("");
  const [teacherAllowed, setTeacherAllowed] = useState(false);
  const [studentAllowed, setStudentAllowed] = useState(false);
  const [objective, setObjective] = useState("behavior");
  const [hypothesis, setHypothesis] = useState(mission?.success ?? "");
  const [approvedBy, setApprovedBy] = useState("");
  const [noMutableFactsConfirmed, setNoMutableFactsConfirmed] = useState(false);
  const [minimumQualityGain, setMinimumQualityGain] = useState(0.05);
  const [temperature, setTemperature] = useState(0);
  const [maxNewTokens, setMaxNewTokens] = useState(512);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    const selectedCheck = brokerChecks.find((record) => record.record_id === brokerCheckId);
    const observedEndpoint = selectedCheck?.summary.endpoint;
    if (typeof observedEndpoint === "string" && observedEndpoint.trim()) {
      setTeacherBrokerEndpoint(observedEndpoint);
    } else {
      setTeacherBrokerEndpoint(configuredBrokerEndpoint);
    }
  }, [brokerCheckId, brokerChecks, configuredBrokerEndpoint]);
  const sha = /^[0-9a-f]{64}$/;
  const teacherReady = teacherSource === "broker"
    ? brokerCheckId && teacherBrokerEndpoint.trim() && teacherProvider.trim() && teacherDeployment.trim()
    : sha.test(teacherFingerprint);
  const valid = datasetId && preflightJobId && baselineExperimentId && teacherModel.trim() && studentModel.trim() && teacherModel.trim() !== studentModel.trim() && teacherReady && sha.test(studentFingerprint) && teacherLicense.trim() && studentLicense.trim() && teacherAllowed && studentAllowed && hypothesis.trim() && approvedBy.trim() && noMutableFactsConfirmed && Number.isFinite(minimumQualityGain) && minimumQualityGain > 0 && minimumQualityGain <= 1;
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
        objective, hypothesis, containsMutableFacts: false, minimumQualityGain, approvedBy, epochs: 1,
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
      <label><span>Baseline comparable</span><select value={baselineExperimentId} onChange={(event) => setBaselineExperimentId(event.target.value)}><option value="">Selecciona</option>{eligibleBaselines.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label>
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
      <label className="confirmation"><input type="checkbox" checked={noMutableFactsConfirmed} onChange={(event) => setNoMutableFactsConfirmed(event.target.checked)} /><span>Confirmo que este objetivo no memoriza hechos cambiantes del vault.</span></label>
      <label><span>Mejora mínima de verificación de formato y citas (0–1)</span><input type="number" min={0.01} max={1} step={0.01} value={minimumQualityGain} onChange={(event) => setMinimumQualityGain(Number(event.target.value))} /></label>
      <div className="distillation-generation"><label><span>Temperatura profesor</span><input type="number" min={0} max={2} step={0.1} value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></label><label><span>Máximo de tokens</span><input type="number" min={1} max={8192} value={maxNewTokens} onChange={(event) => setMaxNewTokens(Number(event.target.value))} /></label></div>
      <button onClick={() => void run()} disabled={busy || !valid}>{busy ? "Enviando…" : "Autorizar destilación"}</button>
    </fieldset></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}
  </section>;
}
