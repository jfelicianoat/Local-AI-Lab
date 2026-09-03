/* Piezas de lectura compartidas: dependencias, evidencia y nodos. */

import { Archive } from "lucide-react";

import type { EvidenceItem, EvidenceStatus, Overview, ProductRecord } from "./contracts";
import { humanize, recordStatus, summaryRows } from "./format";
import { formatTime, statusLabel } from "./states";
export function DependencySummary({ overview }: { overview: Overview }) {
  return <section className="dependency-summary"><h3>Dependencias externas</h3><dl className="dependencies"><div><dt>AI Broker</dt><dd>{overview.external_dependencies.ai_broker}</dd></div><div><dt>Vault</dt><dd>{overview.external_dependencies.vault}</dd></div><div><dt>Model Drift</dt><dd>{overview.external_dependencies.model_drift}</dd></div></dl><div className="truth-note"><strong>Sin suposiciones silenciosas</strong><p>“Unknown” significa pendiente de prueba, no ausente ni incompatible.</p></div></section>;
}

export function StatusCount({ status, label, count }: { status: EvidenceStatus; label: string; count: number }) {
  return <div className={`status-count ${status}`}><span aria-hidden="true" /> <strong>{label}</strong><b>{count}</b></div>;
}

export function EvidenceTable({ items }: { items: EvidenceItem[] }) {
  return <div className="table-wrap"><table><caption>Evidencia necesaria para cerrar la fase actual</caption><thead><tr><th>Control</th><th>Estado</th><th>Procedencia recuperable</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.label}</td><td><span className={`stamp ${item.status}`}>{statusLabel(item.status)}</span></td><td>{item.artifact_sha256 ? <><code title={item.artifact_sha256}>sha256:{item.artifact_sha256.slice(0, 12)}…</code><small>{item.source_reference}</small><small>{item.observed_at ? formatTime(item.observed_at) : null}</small></> : <span className="not-recorded">Aún no registrada</span>}</td></tr>)}</tbody></table></div>;
}

export function NodeTable({ nodes }: { nodes: Overview["nodes"] }) {
  return <section className="nodes-section"><h3>Nodos registrados</h3>{nodes.length ? <div className="table-wrap"><table><thead><tr><th>Equipo</th><th>Estado</th><th>Capacidades</th><th>Último heartbeat</th></tr></thead><tbody>{nodes.map((node) => <tr key={node.node_id}><td><strong>{node.hostname}</strong><code>{node.node_id}</code></td><td>{node.status}</td><td><span className={`stamp ${node.tested_workloads.length ? "tested" : node.capabilities_observed ? "detected" : "pending"}`}>{node.tested_workloads.length ? "PROBADAS" : node.capabilities_observed ? "DETECTADAS" : "PENDIENTES"}</span>{node.tested_workloads.length ? <small>{node.tested_workloads.join(" · ")}</small> : null}</td><td>{formatTime(node.last_heartbeat_at)}</td></tr>)}</tbody></table></div> : <p className="empty-row">No hay nodos reales registrados. El sistema no mostrará workers simulados como evidencia.</p>}</section>;
}

export function RecordBoard({ records, emptyTitle, emptyText }: { records: ProductRecord[]; emptyTitle: string; emptyText: string }) {
  if (!records.length) return <div className="record-empty"><Archive aria-hidden="true" size={24} /><div><strong>{emptyTitle}</strong><p>{emptyText}</p></div></div>;
  return <div className="record-grid">{records.map((record) => <article className="record-card" key={record.record_id}><div className="record-card-head"><span className="record-kind">{record.category}</span><span className={`stamp ${recordStatus(record.status)}`}>{record.status}</span></div><h3>{record.title}</h3><dl>{summaryRows(record.summary).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value}</dd></div>)}</dl><footer><code title={record.artifact_sha256}>sha256:{record.artifact_sha256.slice(0, 12)}…</code><time>{formatTime(record.updated_at)}</time></footer></article>)}</div>;
}
