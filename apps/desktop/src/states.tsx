/* Estados de la superficie: cargando, vacio, error y evidencia caduca. */

import type { EvidenceStatus } from "./contracts";
export function GateState({ status }: { status?: string }) {
  const open = status === "open";
  return <div className={`gate-state ${open ? "open" : "closed"}`}><span aria-hidden="true" /><div><strong>{open ? "Puerta abierta" : "Puerta pendiente"}</strong><small>{status ?? "Coordinator no observado"}</small></div></div>;
}

export function LoadingState() { return <div className="state-panel" role="status"><strong>Iniciando el Coordinator local…</strong><p>La vista aparecerá cuando el sidecar responda con un contrato válido.</p></div>; }
export function EmptyState() { return <div className="state-panel"><strong>Sin evidencia disponible</strong><p>Registra un nodo o ejecuta un probe para empezar.</p></div>; }
export function ErrorState({ message, retry }: { message: string; retry: () => void }) { return <div className="state-panel error" role="alert"><strong>No se pudo abrir la mesa de evidencia</strong><p>{message}</p><button onClick={retry}>Reintentar conexión</button></div>; }
export function StaleState({ message, retry }: { message: string; retry: () => void }) { return <div className="stale-banner" role="status"><div><strong>Mostrando la última evidencia recibida</strong><span>{message}</span></div><button onClick={retry}>Volver a intentar</button></div>; }
export function statusLabel(status: EvidenceStatus) { return ({ tested: "PROBADO", detected: "DETECTADO", pending: "PENDIENTE", blocked: "BLOQUEADO" } as const)[status]; }
export function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "medium" }).format(date); }
