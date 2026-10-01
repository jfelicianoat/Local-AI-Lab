import { useEffect, useState } from "react";
import { createModelExport } from "./api";
import type { Overview, ProductRecord } from "./contracts";

const formats = [
  { id: "adapter", title: "Adaptador LoRA" },
  { id: "merged_model", title: "Modelo completo" },
  { id: "safetensors", title: "Pesos safetensors" },
  { id: "gguf", title: "GGUF" },
];

export function ExportPanel({ records, nodes, onChanged }: {
  records: ProductRecord[]; nodes: Overview["nodes"]; onChanged: () => void;
}) {
  const training = records.filter((record) => ["TRAINING_SUCCEEDED", "DISTILLATION_SUCCEEDED"].includes(record.status));
  const workers = nodes.filter((node) => node.status === "online" && node.capabilities_observed);
  const [trainingId, setTrainingId] = useState(training[0]?.record_id ?? "");
  const [nodeId, setNodeId] = useState(workers[0]?.node_id ?? "");
  const [selectedFormats, setSelectedFormats] = useState<string[]>(["adapter"]);
  const [licenseId, setLicenseId] = useState("");
  const [runtime, setRuntime] = useState("transformers");
  const [converter, setConverter] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (!training.some((item) => item.record_id === trainingId)) setTrainingId(training[0]?.record_id ?? "");
    if (!workers.some((item) => item.node_id === nodeId)) setNodeId(workers[0]?.node_id ?? "");
  }, [records, nodes, trainingId, nodeId]);
  const worker = workers.find((node) => node.node_id === nodeId);
  const pending = selectedFormats.filter((format) => !worker?.tested_workloads.includes(`export.${format}`));
  const ready = Boolean(trainingId && worker && selectedFormats.length && licenseId.trim() && runtime.trim()
    && (!selectedFormats.includes("gguf") || converter.trim()));
  const toggle = (format: string) => setSelectedFormats((current) =>
    current.includes(format) ? current.filter((item) => item !== format) : [...current, format]);
  const run = async (verify: boolean) => {
    setBusy(true); setMessage(null);
    try {
      await createModelExport({ trainingJobId: trainingId, nodeId, formats: selectedFormats,
        licenseId: licenseId.trim(), servingRuntime: runtime.trim(), llamaCppConverter: converter,
        verificationOnly: verify });
      setMessage(`${verify ? "Comprobación de exportación" : "Exportación"} enviada a ${worker?.hostname ?? nodeId}. Sigue su progreso en la actividad.`);
      onChanged();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo iniciar la exportación."); }
    finally { setBusy(false); }
  };
  return <fieldset disabled={busy}>
    <legend>3 · Exportación experimental verificable</legend>
    <label><span>Entrenamiento completado</span><select value={trainingId} onChange={(event) => setTrainingId(event.target.value)}>
      <option value="">Selecciona</option>{training.map((item) => <option key={item.record_id} value={item.record_id}>{item.title} · {item.record_id.slice(0, 8)}</option>)}
    </select></label>
    <label><span>Equipo para la exportación</span><select value={nodeId} onChange={(event) => setNodeId(event.target.value)}>
      <option value="">Selecciona</option>{workers.map((node) => <option key={node.node_id} value={node.node_id}>{node.hostname}</option>)}
    </select></label>
    {!training.length ? <p>Completa primero un entrenamiento o una destilación con resultado validado.</p> : null}
    {!workers.length ? <p>Conecta un Worker y actualiza su información para exportar.</p> : null}
    <div className="format-picker"><span>Formatos</span>{formats.map((format) => <label key={format.id}>
      <input type="checkbox" checked={selectedFormats.includes(format.id)} onChange={() => toggle(format.id)} />
      {format.title}{worker ? (worker.tested_workloads.includes(`export.${format.id}`) ? " · probado" : " · pendiente de comprobación") : ""}
    </label>)}</div>
    <label><span>Licencia</span><input value={licenseId} onChange={(event) => setLicenseId(event.target.value)} placeholder="p. ej. apache-2.0" /></label>
    <label><span>Motor para usar el modelo</span><input value={runtime} onChange={(event) => setRuntime(event.target.value)} /></label>
    {selectedFormats.includes("gguf") ? <label><span>Ruta del conversor llama.cpp en el equipo seleccionado</span>
      <input value={converter} onChange={(event) => setConverter(event.target.value)} /></label> : null}
    {pending.length ? <p role="status">Falta comprobar {pending.map((id) => formats.find((item) => item.id === id)?.title).join(", ")} en este equipo. Usa la comprobación inicial.</p> : null}
    <button type="button" onClick={() => void run(true)} disabled={busy || !ready}>
      {busy ? "Enviando…" : pending.length ? "Comprobar y crear primer paquete" : "Volver a comprobar la exportación"}
    </button>
    <button type="button" onClick={() => void run(false)} disabled={busy || !ready || pending.length > 0}>
      Crear paquete exportable
    </button>
    <p>La comprobación realiza la conversión completa y genera un paquete para guardar. Puede tardar y necesitar mucha memoria. El formato se marca como probado al validar el resultado.</p>
    <p>El paquete es experimental. Evalúalo con F1/F2 y revisión humana antes de promocionarlo.</p>
    {message ? <p className="knowledge-message" role="status">{message}</p> : null}
  </fieldset>;
}
