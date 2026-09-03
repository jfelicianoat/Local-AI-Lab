/* Conocimiento indexado y cola de revision humana. */
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import {
  changeReviewState,
  changeTrainingState,
  createKnowledgeIndex,
  createVaultSnapshot,
  discoverVaults,
  saveReviewCorrection,
} from "./api";
import type { ProductRecord, ReviewRecord } from "./contracts";
import { recordStatus } from "./format";

import { RecordBoard } from "./overview";
export function KnowledgeBoard({ records, onCreated }: { records: ProductRecord[]; onCreated: (record: ProductRecord) => void }) {
  const [root, setRoot] = useState("Y:\\Mi unidad\\Vaults");
  const [vaults, setVaults] = useState<string[]>([]);
  const [vault, setVault] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const snapshots = records.filter((record) => record.category === "snapshot" && record.status === "COMPLETE");
  const indexes = records.filter((record) => record.category === "index");
  const act = async (operation: () => Promise<void>) => {
    setBusy(true); setMessage(null);
    try { await operation(); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo completar la operación."); }
    finally { setBusy(false); }
  };
  const discover = () => void act(async () => {
    const found = await discoverVaults(root);
    setVaults(found); setVault(found[0] ?? "");
    setMessage(found.length ? `${found.length} vault(s) disponible(s).` : "No se encontraron vaults hijos en esa raíz.");
  });
  const snapshot = () => void act(async () => {
    const created = await createVaultSnapshot(root, vault);
    onCreated(created); setSnapshotId(created.record_id);
    setMessage(created.status === "COMPLETE" ? "Snapshot verificado. El vault no se modificó." : "El snapshot no convergió y quedó marcado INCOMPLETE.");
  });
  const index = () => void act(async () => {
    const previous = indexes[0]?.record_id;
    const created = await createKnowledgeIndex(snapshotId, previous);
    onCreated(created); setMessage(previous ? "Nueva generación incremental del índice creada." : "Índice local creado.");
  });
  return <><div className="knowledge-controls"><label><span>Raíz permitida de vaults</span><input value={root} onChange={(event) => setRoot(event.target.value)} disabled={busy} /></label><button onClick={discover} disabled={busy || !root.trim()}>Buscar vaults</button><label><span>Vault</span><select value={vault} onChange={(event) => setVault(event.target.value)} disabled={busy || !vaults.length}><option value="">Selecciona un vault</option>{vaults.map((name) => <option value={name} key={name}>{name}</option>)}</select></label><button onClick={snapshot} disabled={busy || !vault}>Crear snapshot read-only</button><label><span>Snapshot completo</span><select value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} disabled={busy || !snapshots.length}><option value="">Selecciona un snapshot</option>{snapshots.map((item) => <option value={item.record_id} key={item.record_id}>{item.title} · {item.artifact_sha256.slice(0, 8)}</option>)}</select></label><button onClick={index} disabled={busy || !snapshotId}>Construir índice</button></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}<RecordBoard records={records} emptyTitle="Todavía no hay snapshots registrados" emptyText="El snapshot se crea en almacenamiento local separado. La aplicación no expone operaciones de escritura sobre el vault." /></>;
}

export function ReviewBoard({ reviews, onChanged }: { reviews: ReviewRecord[]; onChanged: (review: ReviewRecord) => void }) {
  const [selectedId, setSelectedId] = useState(reviews[0]?.review_id ?? "");
  const selected = reviews.find((item) => item.review_id === selectedId) ?? reviews[0];
  const [editor, setEditor] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (selected) setEditor(JSON.stringify(selected.corrected ?? selected.original, null, 2));
  }, [selected?.review_id, selected?.updated_at]);
  if (!reviews.length) return <div className="review-empty"><div className="review-example"><span>Original</span><p>La respuesta aparecerá aquí cuando exista una ejecución real.</p></div><div className="review-arrow" aria-hidden="true"><ArrowRight size={22} /></div><div className="review-example corrected"><span>Corrección con evidencia</span><p>Ningún candidato pasa a training sin una revisión aceptada y otra aprobación explícita.</p></div></div>;
  if (!selected) return null;
  const perform = async (operation: () => Promise<ReviewRecord>, success: string) => {
    setBusy(true); setMessage(null);
    try { const changed = await operation(); onChanged(changed); setMessage(success); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo completar la operación."); }
    finally { setBusy(false); }
  };
  const save = () => {
    try {
      const parsed: unknown = JSON.parse(editor);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("La corrección debe ser un objeto JSON.");
      void perform(() => saveReviewCorrection(selected.review_id, parsed as Record<string, unknown>), "Corrección guardada y verificada.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "JSON no válido."); }
  };
  return <div className="review-workbench"><aside className="review-queue" aria-label="Cola de revisiones">{reviews.map((review) => <button key={review.review_id} className={review.review_id === selected.review_id ? "active" : ""} onClick={() => setSelectedId(review.review_id)}><strong>{review.case_id}</strong><span>{review.status} · training {review.training_state}</span></button>)}</aside><div className="review-editor"><div className="review-meta"><span className={`stamp ${recordStatus(selected.status)}`}>{selected.status}</span><span className={`stamp ${recordStatus(selected.training_state)}`}>training {selected.training_state}</span><code>{selected.snapshot_id}</code></div><div className="review-columns"><label><span>Respuesta original</span><pre>{JSON.stringify(selected.original, null, 2)}</pre></label><label><span>Corrección</span><textarea value={editor} onChange={(event) => setEditor(event.target.value)} spellCheck={false} disabled={busy || selected.status === "accepted"} /></label></div><div className="review-verification"><strong>{selected.verification?.deterministic_pass ? "Evidencia verificada" : "Pendiente de verificación"}</strong><span>{selected.diff_text ? "El diff está registrado y es recuperable." : "Guarda la corrección para generar el diff."}</span></div>{message ? <p className="review-message" role="status">{message}</p> : null}<div className="review-actions"><button onClick={save} disabled={busy || selected.status === "accepted"}>Guardar y verificar</button><button onClick={() => void perform(() => changeReviewState(selected.review_id, "submitted"), "Enviada a aprobación.")} disabled={busy || selected.status !== "draft" || !selected.verification?.deterministic_pass}>Enviar revisión</button><button onClick={() => void perform(() => changeReviewState(selected.review_id, "accepted"), "Revisión aceptada.")} disabled={busy || selected.status !== "submitted"}>Aceptar revisión</button><button onClick={() => void perform(() => changeTrainingState(selected.review_id, "proposed"), "Candidato propuesto; todavía no está aprobado.")} disabled={busy || selected.status !== "accepted" || selected.training_state !== "excluded"}>Proponer para training</button><button onClick={() => void perform(() => changeTrainingState(selected.review_id, "approved"), "Candidato aprobado explícitamente.")} disabled={busy || selected.training_state !== "proposed"}>Aprobar training</button></div></div></div>;
}
