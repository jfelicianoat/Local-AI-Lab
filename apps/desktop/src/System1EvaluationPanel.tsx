import type { ProductRecord } from "./contracts";

export type EvaluationPolicy = {
  enabled: boolean;
  shadow_mode: boolean;
  threshold: number;
  http_timeout: number;
  require_calibrated: boolean;
  strong_judge_model: { provider: string; deployment: string; model: string } | null;
};

export const defaultEvaluation: EvaluationPolicy = {
  enabled: false, shadow_mode: true, threshold: 0.95, http_timeout: 75,
  require_calibrated: false, strong_judge_model: null,
};

export function System1EvaluationPanel({ value, onChange }: {
  value: EvaluationPolicy; onChange: (policy: EvaluationPolicy) => void;
}) {
  const model = value.strong_judge_model;
  const updateModel = (key: "provider" | "deployment" | "model", text: string) => {
    onChange({ ...value, strong_judge_model: { provider: "", deployment: "", model: "", ...model, [key]: text } });
  };
  return <fieldset className="wide-fieldset">
    <legend>Evaluación con System 1</legend>
    <label><span>Modo de evaluación</span><select
      value={!value.enabled ? "off" : value.shadow_mode ? "shadow" : "active"}
      onChange={(event) => onChange({ ...value, enabled: event.target.value !== "off", shadow_mode: event.target.value !== "active" })}
    >
      <option value="off">Desactivado</option>
      <option value="shadow">Comparar en sombra</option>
      <option value="active">Aceptar juicios de alta confianza</option>
    </select></label>
    {value.enabled ? <>
      <p>Las comprobaciones deterministas se ejecutan primero. El Broker gestiona System 1 y sus proveedores. En sombra, sus etiquetas solo se comparan; las revisiones humanas siguen disponibles.</p>
      <label><span>Confianza mínima para aceptar una etiqueta</span><input type="number" min={0} max={1} step={0.01} value={value.threshold} onChange={(event) => onChange({ ...value, threshold: Number(event.target.value) })} /></label>
      <label><span>Espera máxima de System 1 (segundos)</span><input type="number" min={1} max={3600} value={value.http_timeout} onChange={(event) => onChange({ ...value, http_timeout: Number(event.target.value) })} /></label>
      <label className="confirmation"><input type="checkbox" checked={value.require_calibrated} onChange={(event) => onChange({ ...value, require_calibrated: event.target.checked })} /><span>Exigir puntuaciones calibradas para aceptar automáticamente</span></label>
      <p>El contrato actual declara puntuaciones sin calibrar. Si exiges calibración, los casos semánticos se enviarán al juez o quedarán pendientes de revisión.</p>
      <label className="confirmation"><input type="checkbox" checked={model !== null} onChange={(event) => onChange({ ...value, strong_judge_model: event.target.checked ? { provider: "", deployment: "", model: "" } : null })} /><span>Usar un juez potente para casos dudosos y para comparar en sombra</span></label>
      {model ? <>
        <label><span>Proveedor del juez</span><input value={model.provider} onChange={(event) => updateModel("provider", event.target.value)} /></label>
        <label><span>Deployment del juez</span><input value={model.deployment} onChange={(event) => updateModel("deployment", event.target.value)} /></label>
        <label><span>Modelo del juez</span><input value={model.model} onChange={(event) => updateModel("model", event.target.value)} /></label>
      </> : <p>Sin juez configurado, los casos dudosos conservan el flujo de revisión anterior.</p>}
    </> : null}
  </fieldset>;
}

const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
const percent = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)} %` : "Sin medir";

export function System1Metrics({ record }: { record: ProductRecord }) {
  const metrics = object(record.summary.evaluation_metrics);
  if (!metrics) return <span>Evaluación anterior</span>;
  const rates = object(metrics.rates);
  const policy = object(record.summary.evaluation);
  const gold = object(metrics.system1_eligible_gold);
  const shadow = object(metrics.shadow_vs_strong_judge);
  return <div>
    <span>{policy?.shadow_mode === true ? "En sombra" : "Activo"} · {String(metrics.total ?? 0)} casos</span>
    <small>Determinista {percent(rates?.deterministic)} · System 1 {percent(rates?.system1)}</small>
    <small>Juez {percent(rates?.strong_judge)} · Pendiente {percent(rates?.previous_flow)}</small>
    <small>Escalado {percent(metrics.escalation_rate)}</small>
    <small>Acuerdo System 1 / gold {percent(gold?.agreement)} ({String(gold?.compared ?? 0)} casos)</small>
    <small>Acuerdo con juez {percent(shadow?.agreement)} ({String(shadow?.compared ?? 0)} casos)</small>
    <small>Coste de evaluación sin medir</small>
  </div>;
}
