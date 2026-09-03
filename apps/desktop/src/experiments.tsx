/* Experimentos: comparativas, compatibilidad del Broker y suites. */
import { useState } from "react";
import { Activity } from "lucide-react";
import {
  checkBrokerCompatibility,
  createBrokerAgentExperiment,
  createSemanticRetrievalBenchmark,
  createStrategyRun,
  registerRealBenchmark,
  runControlledRetrievalBenchmark,
  runModelDriftComparison,
  selectStrategy,
} from "./api";
import type { Overview, ProductRecord } from "./contracts";
import { caseCount, configurationName, formatMetric } from "./format";

import { RecordBoard } from "./overview";
export function ExperimentBoard({ records, snapshots, nodes, onCreated }: { records: ProductRecord[]; snapshots: ProductRecord[]; nodes: Overview["nodes"]; onCreated: (record: ProductRecord) => void }) {
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
  return <><div className="experiment-caveat"><Activity aria-hidden="true" size={20} /><div><strong>R3 y R4 no tienen un ganador general</strong><p>Cada resultado pertenece a una configuración exacta de embeddings, k, suite y snapshot. Con muestras pequeñas la aplicación mostrará incertidumbre y no afirmará que el grafo mejora de forma estable.</p></div></div><div className="operation-forms experiment-forms"><fieldset><legend>R1 · baseline lexical</legend><label><span>Profundidad de retrieval (k)</span><input type="number" min={1} max={100} value={k} onChange={(event) => setK(Math.max(1, Math.min(100, Number(event.target.value))))} disabled={busy} /></label><button onClick={() => void run()} disabled={busy}>{busy ? "Trabajando…" : "Ejecutar R1 controlado"}</button><p>Se ejecuta localmente sobre un snapshot sintético; no usa AI Broker ni el vault real.</p></fieldset><fieldset><legend>R2–R4 · retrieval con embeddings</legend><label><span>Estrategia</span><select value={semanticStrategy} onChange={(event) => setSemanticStrategy(event.target.value as "R2" | "R3" | "R4")}><option value="R2">R2 · semántico</option><option value="R3">R3 · híbrido</option><option value="R4">R4 · híbrido + grafo</option></select></label><label><span>Worker</span><select value={semanticNode} onChange={(event) => setSemanticNode(event.target.value)}><option value="">Selecciona</option>{nodes.map((node) => <option key={node.node_id} value={node.node_id}>{node.hostname}</option>)}</select></label><label><span>Modelo de embeddings local exacto</span><input value={embeddingModel} onChange={(event) => setEmbeddingModel(event.target.value)} placeholder="ruta o ID ya presente en caché" /></label><label><span>SHA-256 del modelo/cache</span><input value={embeddingFingerprint} onChange={(event) => setEmbeddingFingerprint(event.target.value.toLowerCase())} maxLength={64} /></label><label><span>Dispositivo probado</span><input value={embeddingDevice} onChange={(event) => setEmbeddingDevice(event.target.value)} placeholder="cpu, cuda o mps" /></label><button onClick={() => void runSemantic()} disabled={busy || !semanticNode || !embeddingModel.trim() || !/^[0-9a-f]{64}$/.test(embeddingFingerprint) || !embeddingDevice.trim()}>Enviar benchmark</button><p>El Worker debe publicar <code>embeddings.semantic</code> como probado; no se descarga ningún modelo.</p></fieldset><fieldset className="wide-fieldset"><legend>Benchmark A · vault real</legend><p>La referencia debe estar escrita y aprobada por una persona; la aplicación valida cada evidencia contra un snapshot completo.</p><button onClick={prepareRealTemplate} disabled={busy || snapshots.length === 0}>Preparar plantilla del snapshot</button><label><span>Definición revisada</span><textarea className="definition-editor" value={realDefinition} onChange={(event) => setRealDefinition(event.target.value)} spellCheck={false} placeholder="Prepara la plantilla y completa consulta, autor, respuesta y evidencias." /></label><button onClick={() => void saveReal()} disabled={busy || !realDefinition.trim()}>Validar y registrar benchmark real</button></fieldset><fieldset className="wide-fieldset"><legend>Evaluación formal · Model Drift</legend><p>Solo se aceptan parejas con el mismo embedding, k, suite, snapshot y modelo generativo. Así se aísla el efecto de añadir el grafo.</p><label><span>R3 completado</span><select value={r3Id} onChange={(event) => setR3Id(event.target.value)}><option value="">Selecciona</option>{r3Runs.map((item) => <option key={item.record_id} value={item.record_id}>{configurationName(item)}</option>)}</select></label><label><span>R4 completado</span><select value={r4Id} onChange={(event) => setR4Id(event.target.value)}><option value="">Selecciona</option>{r4Runs.map((item) => <option key={item.record_id} value={item.record_id}>{configurationName(item)}</option>)}</select></label><label><span>Ejecutable público de Model Drift</span><input value={driftExecutable} onChange={(event) => setDriftExecutable(event.target.value)} /></label><label><span>Carpeta de Model Drift</span><input value={driftDirectory} onChange={(event) => setDriftDirectory(event.target.value)} /></label><label className="confirmation"><input type="checkbox" checked={driftConfirmed} onChange={(event) => setDriftConfirmed(event.target.checked)} /><span>Confirmo la ejecución externa mediante el CLI público; no se leerá su base de datos.</span></label><button onClick={() => void compareFormal()} disabled={busy || !r3Id || !r4Id || !driftExecutable.trim() || !driftDirectory.trim() || !driftConfirmed}>Ejecutar comparación formal</button></fieldset></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}{experimentRecords.length ? <ComparisonTable records={experimentRecords} /> : <RecordBoard records={[]} emptyTitle="Todavía no hay ensayos comparables" emptyText="Ejecuta R1 y después R2–R4 con un Worker y modelo local probados." />}</>;
}

export function ComparisonTable({ records }: { records: ProductRecord[] }) {
  return <div className="table-wrap comparison-table"><table><caption>Trade-offs por configuración exacta, sin score global</caption><thead><tr><th>Configuración</th><th>Calidad retrieval</th><th>Muestra</th><th>Coste</th><th>Estado formal</th><th>Evidencia</th></tr></thead><tbody>{records.map((record) => { const cases = caseCount(record); return <tr key={record.record_id}><td><strong>{configurationName(record)}</strong><small>{record.status}</small></td><td><span>Recall@k {formatMetric(record.summary.recall_at_k)}</span><small>Precision {formatMetric(record.summary.precision_at_k)} · MRR {formatMetric(record.summary.mrr)} · nDCG {formatMetric(record.summary.ndcg_at_k)}</small></td><td><span>{cases || "—"} casos</span><small>{cases > 0 && cases < 20 ? "Potencia insuficiente para generalizar" : "Umbral declarable según el estudio"}</small></td><td>{String(record.summary.cost ?? record.summary.cost_amount ?? "unknown")}</td><td>{String(record.summary.formal_status ?? "unverified")}</td><td><code title={record.artifact_sha256}>sha256:{record.artifact_sha256.slice(0, 12)}…</code></td></tr>; })}</tbody></table></div>;
}

export function BrokerCompatibilityPanel({ onCreated }: { onCreated: (record: ProductRecord) => void }) {
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

export function StrategySelectorPanel({ records, onCreated }: { records: ProductRecord[]; onCreated: (record: ProductRecord) => void }) {
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
  return <section className="selector-panel"><h3>Selector de configuración · recomendación explicable</h3><p>Compara configuraciones completas, no nombres aislados como R3 o R4. No se activa hasta que la evidencia sea comparable y conserva la incertidumbre.</p><div className="selector-options">{eligible.map((record) => <label key={record.record_id}><input type="checkbox" checked={selected.includes(record.record_id)} onChange={() => toggle(record.record_id)} /><span>{configurationName(record)}</span></label>)}</div><div className="knowledge-controls"><label><span>Mínimo de casos comparables</span><input type="number" min={1} value={minimumCases} onChange={(event) => setMinimumCases(Math.max(1, Number(event.target.value)))} /></label><label className="confirmation"><input type="checkbox" checked={formal} onChange={(event) => setFormal(event.target.checked)} /><span>Exigir veredicto formal de Model Drift</span></label><button onClick={() => void decide()} disabled={busy || selected.length < 2}>{busy ? "Evaluando…" : "Generar recomendación"}</button></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}</section>;
}

export function AgentExperimentPanel({ records, nodes, onCreated }: { records: ProductRecord[]; nodes: Overview["nodes"]; onCreated: (record: ProductRecord) => void }) {
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

export function StrategyRunnerPanel({ records, training, nodes, onCreated }: { records: ProductRecord[]; training: ProductRecord[]; nodes: Overview["nodes"]; onCreated: (record: ProductRecord) => void }) {
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
