/* Piezas de lectura compartidas: dependencias, evidencia y nodos. */

import { useState } from "react";
import { Archive } from "lucide-react";
import { saveProductArtifact } from "./api";

import type { EvidenceItem, EvidenceStatus, Overview, ProductRecord, StorageStatus } from "./contracts";
import { humanize, productStatusLabel, recordStatus, summaryRows } from "./format";
import { formatTime, statusLabel } from "./states";
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const unit = bytes < 1024 ** 2 ? "KiB" : bytes < 1024 ** 3 ? "MiB" : "GiB";
  const divisor = unit === "KiB" ? 1024 : unit === "MiB" ? 1024 ** 2 : 1024 ** 3;
  return `${(bytes / divisor).toLocaleString("es-ES", { maximumFractionDigits: 1 })} ${unit}`;
}

export function DependencySummary({ overview, storage }: { overview: Overview; storage: StorageStatus | null }) {
  return <section className="dependency-summary"><h3>Dependencias externas</h3><dl className="dependencies"><div><dt>AI Broker</dt><dd>{overview.external_dependencies.ai_broker}</dd></div><div><dt>Vault</dt><dd>{overview.external_dependencies.vault}</dd></div><div><dt>Model Drift</dt><dd>{overview.external_dependencies.model_drift}</dd></div></dl><div className="truth-note"><strong>Sin suposiciones silenciosas</strong><p>“Unknown” significa pendiente de prueba, no ausente ni incompatible.</p></div>{storage ? <><h3>Almacenamiento de artefactos</h3><dl className="dependencies"><div><dt>Guardados</dt><dd>{formatSize(storage.committed_bytes)}</dd></div><div><dt>Reservado para transferencias</dt><dd>{formatSize(storage.pending_reserved_bytes)}</dd></div><div><dt>Fragmentos temporales</dt><dd>{formatSize(storage.temporary_chunk_bytes)}</dd></div><div><dt>Limpieza pendiente</dt><dd>{formatSize(storage.cleanup_pending_bytes)}</dd></div><div><dt>Disponible dentro del límite</dt><dd>{formatSize(storage.available_quota_bytes)}</dd></div><div><dt>Espacio libre en disco</dt><dd>{formatSize(storage.free_disk_bytes)}</dd></div></dl><p>Límite del almacén: {formatSize(storage.quota_bytes)}. Las transferencias nuevas se rechazan si superan el límite o el espacio libre necesario.</p></> : null}</section>;
}

export function StatusCount({ status, label, count }: { status: EvidenceStatus; label: string; count: number }) {
  return <div className={`status-count ${status}`}><span aria-hidden="true" /> <strong>{label}</strong><b>{count}</b></div>;
}

export function EvidenceTable({ items }: { items: EvidenceItem[] }) {
  return <div className="table-wrap"><table><caption>Evidencia necesaria para cerrar la fase actual</caption><thead><tr><th>Control</th><th>Estado</th><th>Procedencia recuperable</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.label}</td><td><span className={`stamp ${item.status}`}>{statusLabel(item.status)}</span></td><td>{item.artifact_sha256 ? <><code title={item.artifact_sha256}>sha256:{item.artifact_sha256.slice(0, 12)}…</code><small>{item.source_reference}</small><small>{item.observed_at ? formatTime(item.observed_at) : null}</small></> : <span className="not-recorded">Aún no registrada</span>}</td></tr>)}</tbody></table></div>;
}

export function NodeTable({ nodes, onRevoke }: { nodes: Overview["nodes"]; onRevoke?: (nodeId: string) => void }) {
  return <section className="nodes-section">
    <h3>Nodos registrados</h3>
    {nodes.length ? <div className="table-wrap"><table>
      <thead><tr><th>Equipo</th><th>Estado</th><th>Capacidades</th><th>Último heartbeat</th>{onRevoke ? <th>Acción</th> : null}</tr></thead>
      <tbody>{nodes.map((node) => <tr key={node.node_id}>
        <td><strong>{node.hostname}</strong><code>{node.node_id}</code></td>
        <td>{node.status}</td>
        <td>
          <span className={`stamp ${node.tested_workloads.length ? "tested" : node.capabilities_observed ? "detected" : "pending"}`}>
            {node.tested_workloads.length ? "PROBADAS" : node.capabilities_observed ? "DETECTADAS" : "PENDIENTES"}
          </span>
          {node.tested_workloads.length ? <small>{node.tested_workloads.join(" · ")}</small> : null}
          {node.capability_warning ? <small role="status">{node.capability_warning}</small> : null}
        </td>
        <td>{formatTime(node.last_heartbeat_at)}</td>
        {onRevoke ? <td><button onClick={() => onRevoke(node.node_id)} disabled={node.status === "revoked"}>
          {node.status === "revoked" ? "Revocado" : "Revocar acceso"}
        </button></td> : null}
      </tr>)}</tbody>
    </table></div> : <p className="empty-row">No hay nodos reales registrados. El sistema no mostrará workers simulados como evidencia.</p>}
  </section>;
}

export function RecordBoard({ records, emptyTitle, emptyText }: { records: ProductRecord[]; emptyTitle: string; emptyText: string }) {
  if (!records.length) return <div className="record-empty"><Archive aria-hidden="true" size={24} /><div><strong>{emptyTitle}</strong><p>{emptyText}</p></div></div>;
  return <div className="record-grid">{records.map((record) => <article className="record-card" key={record.record_id}><div className="record-card-head"><span className="record-kind">{record.category}</span><span className={`stamp ${recordStatus(record.status)}`}>{productStatusLabel(record.status)}</span></div><h3>{record.title}</h3>{record.status === "RESULT_REQUIRES_VALIDATION" ? <p role="status">Los archivos se conservan. Este resultado no autoriza nuevos trabajos; repite la prueba o ejecución necesaria.</p> : null}<dl>{summaryRows(record.summary).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value}</dd></div>)}</dl><footer><code title={record.artifact_sha256}>sha256:{record.artifact_sha256.slice(0, 12)}…</code><time>{formatTime(record.updated_at)}</time></footer><SaveArtifactButton record={record} /></article>)}</div>;
}

export function SaveArtifactButton({ record }: { record: ProductRecord }) {
  const available = (record.category === "experiment" && ["LOCAL_VERIFIED", "PENDING_HUMAN_REVIEW", "EXPERIMENT_SUCCEEDED", "RESULT_REQUIRES_VALIDATION"].includes(record.status)) ||
    (record.category === "export" && ["EXPORT_SUCCEEDED", "RESULT_REQUIRES_VALIDATION"].includes(record.status));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (!available) return null;
  const save = async () => {
    setBusy(true); setMessage("");
    try {
      const path = await saveProductArtifact(record.record_id);
      setMessage(`Guardado en ${path}`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "No se pudo guardar el resultado.");
    } finally { setBusy(false); }
  };
  return <div className="record-download"><button type="button" onClick={() => void save()} disabled={busy}>{busy ? "Guardando…" : record.category === "export" ? "Guardar paquete" : "Guardar informe"}</button>{message ? <small role="status">{message}</small> : null}</div>;
}
