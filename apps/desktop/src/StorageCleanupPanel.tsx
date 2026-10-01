import { useEffect, useState } from "react";
import { applyStorageCleanup, loadPendingStorageCleanup, planStorageCleanup } from "./api";
import type { StorageCleanupPlan } from "./contracts";
import { formatTime } from "./states";

function size(bytes: number): string {
  return `${(bytes / 1024 ** 2).toLocaleString("es-ES", { maximumFractionDigits: 2 })} MiB`;
}

export function StorageCleanupPanel({ onCleaned }: { onCleaned: () => void }) {
  const [days, setDays] = useState(30);
  const [plan, setPlan] = useState<StorageCleanupPlan | null>(null);
  const [busy, setBusy] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void loadPendingStorageCleanup().then((value) => { if (active) setPlan(value); })
      .catch((reason) => { if (active) setError(String(reason)); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);
  async function review() {
    setBusy(true); setError(null); setMessage(null); setConfirmed(false);
    try { setPlan(await planStorageCleanup(days)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }
  async function clean() {
    if (!plan || (!confirmed && plan.status !== "applying")) return;
    setBusy(true); setError(null);
    try {
      const result = await applyStorageCleanup(plan.plan_id);
      setMessage(`Limpieza completada: ${result.removed_count} elementos retirados.${result.skipped_count
        ? ` Se conservaron ${result.skipped_count} elementos que habían cambiado.` : ""}`);
      setPlan(null); setConfirmed(false); onCleaned();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      // Recover durable approval when a response is lost or deletion is interrupted.
      try { const pending = await loadPendingStorageCleanup(); if (pending) setPlan(pending); }
      catch { /* Keep the reviewed plan available for a retry. */ }
    } finally { setBusy(false); }
  }
  return <section className="storage-cleanup" aria-labelledby="cleanup-title">
    <h3 id="cleanup-title">Liberar espacio</h3>
    <p>Revisa transferencias abandonadas y archivos antiguos sin referencias. Se conservan los resultados,
      datasets, evidencias y checkpoints registrados. Esta limpieza se limita al almacén de artefactos.</p>
    <div className="cleanup-actions"><label>Sin actividad durante al menos <select value={days}
      disabled={busy || plan?.status === "applying"} onChange={(event) => setDays(Number(event.target.value))}>
      <option value={30}>30 días</option><option value={60}>60 días</option><option value={90}>90 días</option>
    </select></label><button disabled={busy || plan?.status === "applying"} onClick={() => void review()}>
      Revisar limpieza</button></div>
    {busy ? <p role="status">Comprobando el almacenamiento…</p> : null}
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {plan ? <><p>{plan.status === "applying" ? "Hay una limpieza autorizada pendiente de terminar."
      : `${plan.entries.length} elementos candidatos; ${size(plan.reclaimable_bytes)} en esta propuesta.`}</p>
      {plan.entries.length ? <><div className="cleanup-list table-wrap"><table>
        <caption>Archivos incluidos en la propuesta</caption><thead><tr><th>Tipo</th><th>Identificador</th>
          <th>Tamaño</th><th>Última actividad</th></tr></thead><tbody>{plan.entries.map((item) =>
          <tr key={`${item.kind}:${item.id}`}><td>{item.kind === "blob" ? "Archivo sin referencias" : "Transferencia antigua"}</td>
            <td><code title={item.id}>{item.id}</code>{item.source_job_id ? <small>Trabajo: {item.source_job_id}</small> : null}</td>
            <td>{size(item.bytes)}</td><td>{formatTime(item.last_activity)}</td></tr>)}</tbody></table></div>
        {plan.remaining_count ? <p>Quedan {plan.remaining_count} candidatos para una propuesta posterior.</p> : null}
        {plan.status !== "applying" ? <label className="cleanup-confirm"><input type="checkbox" checked={confirmed}
          disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} />He revisado la lista y autorizo
          el borrado permanente de estos elementos.</label> : null}
        <div className="cleanup-actions"><button disabled={busy || (!confirmed && plan.status !== "applying")}
          onClick={() => void clean()}>{plan.status === "applying" ? "Completar limpieza pendiente" : "Eliminar elementos revisados"}</button>
          {plan.status !== "applying" ? <button disabled={busy} onClick={() => { setPlan(null); setConfirmed(false); }}>Cerrar propuesta</button> : null}
        </div></> : <p>No hay archivos que cumplan esta política de limpieza.</p>}</> : null}
  </section>;
}
