/* Conocimiento indexado y cola de revision humana. */
import { useCallback, useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import {
  changeReviewState,
  changeTrainingState,
  createKnowledgeIndex,
  createManualExample,
  createVaultSnapshot,
  discoverVaults,
  previewManualExample,
  saveReviewCorrection,
  ReviewConflictError,
} from "./api";
import type { ManualExampleHit } from "./api";
import type { ProductRecord, ReviewRecord } from "./contracts";
import { recordStatus } from "./format";
import { editReviewDraft, newReviewDraft, reconcileReviewDraft } from "./reviewDraft";

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

export function ManualExamplePanel({ knowledge, onCreated }: { knowledge: ProductRecord[]; onCreated: (review: ReviewRecord) => void }) {
  const snapshots = knowledge.filter((record) => record.category === "snapshot" && record.status === "COMPLETE");
  const [snapshotId, setSnapshotId] = useState("");
  const indexes = knowledge.filter((record) => record.category === "index" && record.status === "READY" && record.summary.snapshot_id === snapshotId);
  const [indexId, setIndexId] = useState("");
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [reviewer, setReviewer] = useState("desktop-user");
  const [hits, setHits] = useState<ManualExampleHit[]>([]);
  const [selectedChunks, setSelectedChunks] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const preview = async () => {
    setBusy(true); setMessage(null); setHits([]); setSelectedChunks([]);
    try {
      const found = await previewManualExample(snapshotId, indexId, query);
      setHits(found);
      setMessage(found.length ? "Selecciona los fragmentos que respaldan tu respuesta." : "No se encontraron fragmentos para esta consulta.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo buscar en el índice."); }
    finally { setBusy(false); }
  };
  const create = async () => {
    setBusy(true); setMessage(null);
    try {
      const review = await createManualExample({ snapshotId, indexId, query, answer, chunkIds: selectedChunks, reviewer });
      onCreated(review);
      setMessage("Ejemplo creado como borrador. Revisa sus afirmaciones y citas antes de aprobarlo.");
      setAnswer(""); setSelectedChunks([]); setHits([]);
    } catch (error) { setMessage(error instanceof Error ? error.message : "No se pudo crear el ejemplo."); }
    finally { setBusy(false); }
  };
  return <section className="manual-example-panel"><h3>Nueva consulta para entrenamiento</h3><p>Aporta una pregunta distinta de las usadas en benchmarks. Elige evidencia del vault y revisa la respuesta antes de aprobarla para el dataset.</p><div className="knowledge-controls"><label><span>Snapshot</span><select value={snapshotId} onChange={(event) => { setSnapshotId(event.target.value); setIndexId(""); setHits([]); setSelectedChunks([]); }}><option value="">Selecciona</option>{snapshots.map((record) => <option key={record.record_id} value={record.record_id}>{record.title}</option>)}</select></label><label><span>Índice del snapshot</span><select value={indexId} onChange={(event) => { setIndexId(event.target.value); setHits([]); setSelectedChunks([]); }}><option value="">Selecciona</option>{indexes.map((record) => <option key={record.record_id} value={record.record_id}>{record.title} · {record.record_id.slice(0, 8)}</option>)}</select></label><label><span>Pregunta</span><textarea value={query} onChange={(event) => { setQuery(event.target.value); setHits([]); setSelectedChunks([]); }} /></label><button onClick={() => void preview()} disabled={busy || !snapshotId || !indexId || !query.trim()}>Buscar fuentes</button></div>{hits.length ? <div className="manual-example-hits"><h4>Fuentes encontradas</h4>{hits.map((hit) => <label key={hit.chunk_id}><input type="checkbox" checked={selectedChunks.includes(hit.chunk_id)} onChange={() => setSelectedChunks((current) => current.includes(hit.chunk_id) ? current.filter((id) => id !== hit.chunk_id) : [...current, hit.chunk_id])} /><span><strong>{hit.note_path} · {hit.section}</strong><small>{hit.content}</small></span></label>)}</div> : null}<div className="knowledge-controls"><label><span>Respuesta propuesta</span><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} /></label><label><span>Revisor</span><input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><button onClick={() => void create()} disabled={busy || !query.trim() || !answer.trim() || !reviewer.trim() || selectedChunks.length === 0}>Crear borrador de revisión</button></div>{message ? <p className="knowledge-message" role="status">{message}</p> : null}</section>;
}

export function ReviewBoard({ reviews, onChanged, registerExitGuard, onRefresh }: {
  reviews: ReviewRecord[]; onChanged: (review: ReviewRecord) => void;
  registerExitGuard: (guard: (() => boolean) | null) => void;
  onRefresh: () => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState(reviews[0]?.review_id ?? "");
  const selected = reviews.find((item) => item.review_id === selectedId) ?? reviews[0];
  const savedText = selected ? JSON.stringify(selected.corrected ?? selected.original, null, 2) : "";
  const [draft, setDraft] = useState(() => newReviewDraft(selected?.review_id ?? "", savedText, selected?.revision ?? 0));
  const editor = draft.reviewId === selected?.review_id ? draft.text : savedText;
  const setEditor = (text: string) => setDraft((current) => editReviewDraft(current, text));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (selected) setDraft((current) => reconcileReviewDraft(current, selected.review_id, savedText, selected.revision));
  }, [selected?.review_id, selected?.revision, savedText]);
  const dirty = Boolean(selected) && editor !== savedText;
  const conflict = draft.reviewId === selected?.review_id && (draft.conflict ||
    (draft.text !== draft.savedText && (savedText !== draft.savedText || selected?.revision !== draft.savedRevision) && draft.text !== savedText));
  const hasUnsavedChanges = dirty || (selected?.status === "submitted" && Boolean(reason.trim()));
  const canLeave = useCallback(() => {
    if (busy) { setMessage("Espera a que termine la operación antes de cambiar de pantalla o revisión."); return false; }
    return !hasUnsavedChanges || window.confirm("Hay cambios sin guardar en esta revisión. ¿Quieres descartarlos y salir?");
  }, [busy, hasUnsavedChanges]);
  useEffect(() => {
    registerExitGuard(canLeave);
    return () => registerExitGuard(null);
  }, [registerExitGuard, canLeave]);
  useEffect(() => {
    if (!hasUnsavedChanges && !busy) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasUnsavedChanges, busy]);
  if (!reviews.length) return <div className="review-empty"><div className="review-example"><span>Original</span><p>La respuesta aparecerá aquí cuando exista una ejecución real.</p></div><div className="review-arrow" aria-hidden="true"><ArrowRight size={22} /></div><div className="review-example corrected"><span>Corrección con evidencia</span><p>Ningún candidato pasa a training sin una revisión aceptada y otra aprobación explícita.</p></div></div>;
  if (!selected) return null;
  const base = selected.corrected ?? selected.original;
  const editable = !busy && !["accepted", "rejected"].includes(selected.status);
  const context = selected.context;
  const retrieved = Array.isArray(context.retrieved_context) ? context.retrieved_context.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
  let current: Record<string, unknown> = base;
  try {
    const parsed: unknown = JSON.parse(editor);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) current = parsed as Record<string, unknown>;
  } catch { /* The JSON editor shows a validation error on save. */ }
  const findings = Array.isArray(current.findings) ? current.findings.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
  const updateField = (field: string, value: unknown) => setEditor(JSON.stringify({ ...current, [field]: value }, null, 2));
  const chooseReview = (id: string) => {
    if (id === selected.review_id || !canLeave()) return;
    setSelectedId(id); setReason(""); setMessage(null);
  };
  const reloadSaved = () => {
    if (dirty && !window.confirm("Se descartará tu corrección local para cargar la versión guardada. ¿Continuar?")) return;
    setDraft(newReviewDraft(selected.review_id, savedText, selected.revision)); setMessage(null);
  };
  const perform = async (operation: () => Promise<ReviewRecord>, success: string) => {
    setBusy(true); setMessage(null);
    try { const changed = await operation(); onChanged(changed); setMessage(success); }
    catch (error) {
      if (error instanceof ReviewConflictError) await onRefresh();
      setMessage(error instanceof Error ? error.message : "No se pudo completar la operación.");
    }
    finally { setBusy(false); }
  };
  const save = () => {
    if (conflict) { setMessage("Resuelve el cambio de versión antes de guardar la corrección."); return; }
    try {
      const parsed: unknown = JSON.parse(editor);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("La corrección debe ser un objeto JSON.");
      void perform(() => saveReviewCorrection(selected.review_id, parsed as Record<string, unknown>, draft.savedRevision), "Corrección guardada y verificada.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "JSON no válido."); }
  };
  return <div className="review-workbench">
    <aside className="review-queue" aria-label="Cola de revisiones">{reviews.map((review) => <button key={review.review_id} className={review.review_id === selected.review_id ? "active" : ""} onClick={() => chooseReview(review.review_id)}><strong>{String(review.context.query ?? review.case_id)}</strong><span>{review.status} · training {review.training_state}</span></button>)}</aside>
    <div className="review-editor">
      <div className="review-meta"><span className={`stamp ${recordStatus(selected.status)}`}>{selected.status}</span><span className={`stamp ${recordStatus(selected.training_state)}`}>training {selected.training_state}</span><code>{selected.snapshot_id}</code></div>
      <section className="review-evidence"><h3>Pregunta y respuesta</h3><p><strong>Pregunta:</strong> {String(context.query ?? "No registrada")}</p><p><strong>Respuesta original:</strong> {String(selected.original.answer ?? selected.original.raw_response ?? "Sin respuesta estructurada")}</p><details><summary>Prompt enviado al modelo</summary><pre>{String(context.prompt ?? "No registrado")}</pre></details></section>
      <div className="review-columns"><section><h3>Afirmaciones y citas originales</h3>{Array.isArray(selected.original.findings) ? selected.original.findings.map((finding, index) => {
        const claim = finding && typeof finding === "object" ? finding as Record<string, unknown> : {};
        const citations = Array.isArray(claim.evidence) ? claim.evidence : [];
        return <div key={index} className="review-finding"><p>{String(claim.claim ?? "")}</p>{citations.map((citation, citationIndex) => {
          const ref = citation && typeof citation === "object" ? citation as Record<string, unknown> : {};
          return <a key={citationIndex} href={`#review-chunk-${String(ref.chunk_id ?? "")}`}>{String(ref.note_path ?? ref.chunk_id ?? "Cita")}</a>;
        })}</div>;
      }) : <p>No hay afirmaciones estructuradas.</p>}</section><section><h3>Contexto recuperado</h3>{retrieved.length ? retrieved.map((chunk, index) => <article id={`review-chunk-${String(chunk.chunk_id ?? index)}`} key={index} className="review-chunk"><strong>{String(chunk.note_path ?? chunk.chunk_id ?? "Fuente")}</strong><small>{String(chunk.section ?? "")}</small><p>{String(chunk.content ?? "Contenido no incluido")}</p></article>) : <p>Esta ejecución no incluyó contexto recuperado.</p>}</section></div>
      <section className="review-correction"><h3>Corrección</h3><label><span>Respuesta final</span><textarea value={String(current.answer ?? "")} onChange={(event) => updateField("answer", event.target.value)} disabled={!editable} /></label>{findings.map((finding, index) => <label key={index}><span>Afirmación {index + 1} · {Array.isArray(finding.evidence) ? finding.evidence.length : 0} cita(s)</span><input value={String(finding.claim ?? "")} onChange={(event) => updateField("findings", findings.map((item, position) => position === index ? { ...item, claim: event.target.value } : item))} disabled={!editable} /></label>)}<details><summary>Edición avanzada de JSON y citas</summary><textarea value={editor} onChange={(event) => setEditor(event.target.value)} spellCheck={false} disabled={!editable} /></details></section>
      {conflict ? <div className="review-message" role="alert"><p>La versión guardada de esta revisión cambió mientras editabas. Tu corrección local se conserva. Revisa la actualización antes de continuar.</p><button onClick={reloadSaved} disabled={busy}>Cargar la versión guardada</button></div> : null}
      <div className="review-verification"><strong>{selected.verification?.deterministic_pass ? "Estructura y referencias verificadas" : "Pendiente de verificación"}</strong><span>La comprobación automática valida estructura y referencias; no sustituye la revisión humana de los hechos.</span>{selected.verification?.errors?.length ? <ul>{selected.verification.errors.map((error, index) => <li key={index}>{error}</li>)}</ul> : null}{selected.diff_text ? <details><summary>Ver cambios frente al original</summary><pre>{selected.diff_text}</pre></details> : null}{dirty ? <span>Hay cambios sin guardar.</span> : null}</div>
      {message ? <p className="review-message" role="status">{message}</p> : null}
      <div className="review-actions"><button onClick={save} disabled={!editable || !dirty || conflict}>Guardar y verificar</button><button onClick={() => void perform(() => changeReviewState(selected.review_id, "submitted", selected.revision), "Enviada a aprobación.")} disabled={busy || dirty || selected.status !== "draft" || !selected.verification?.deterministic_pass}>Enviar revisión</button><button onClick={() => void perform(() => changeReviewState(selected.review_id, "accepted", selected.revision), "Revisión aceptada.")} disabled={busy || dirty || selected.status !== "submitted"}>Aceptar revisión</button><button onClick={() => void perform(() => changeReviewState(selected.review_id, "draft", selected.revision), "Devuelta a corrección.")} disabled={busy || dirty || !["submitted", "rejected"].includes(selected.status)}>Devolver a borrador</button><label><span>Motivo de rechazo</span><input value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy || selected.status !== "submitted"} /></label><button onClick={() => void perform(() => changeReviewState(selected.review_id, "rejected", selected.revision, reason), "Revisión rechazada con motivo registrado.")} disabled={busy || dirty || selected.status !== "submitted" || !reason.trim()}>Rechazar</button><button onClick={() => void perform(() => changeTrainingState(selected.review_id, "proposed", selected.revision), "Candidato propuesto; todavía no está aprobado.")} disabled={busy || selected.status !== "accepted" || selected.training_state !== "excluded"}>Proponer para training</button><button onClick={() => void perform(() => changeTrainingState(selected.review_id, "approved", selected.revision), "Candidato aprobado explícitamente.")} disabled={busy || selected.training_state !== "proposed"}>Aprobar training</button></div>
    </div>
  </div>;
}
