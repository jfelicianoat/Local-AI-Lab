import { useEffect, useState } from "react";
import { previewManualExample, registerRealBenchmark, type ManualExampleHit } from "./api";
import type { ProductRecord } from "./contracts";

type Case = {
  case_id: string;
  query: string;
  reference_answer: {
    author_kind: "human";
    author: string;
    answer: string;
    evidence: Pick<ManualExampleHit, "note_id" | "note_path" | "section" | "chunk_id" | "source_reference">[];
  };
};

export function RealBenchmarkForm({ knowledge, onCreated }: { knowledge: ProductRecord[]; onCreated: (record: ProductRecord) => void }) {
  const snapshots = knowledge.filter((item) => item.category === "snapshot" && item.status === "COMPLETE");
  const [snapshotId, setSnapshotId] = useState("");
  const snapshot = snapshots.find((item) => item.record_id === snapshotId);
  const indexes = knowledge.filter((item) => item.category === "index" && item.status === "READY" && item.summary.snapshot_id === snapshotId);
  const [indexId, setIndexId] = useState("");
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [author, setAuthor] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [hits, setHits] = useState<ManualExampleHit[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!snapshotId && snapshots.length) setSnapshotId(snapshots[0].record_id);
  }, [snapshotId, snapshots]);
  useEffect(() => {
    if (!indexes.some((item) => item.record_id === indexId)) setIndexId(indexes[0]?.record_id ?? "");
  }, [snapshotId, indexId, knowledge]);
  const search = async () => {
    setBusy(true); setMessage(""); setHits([]); setSelectedIds([]);
    try {
      const found = await previewManualExample(snapshotId, indexId, query);
      setHits(found);
      if (!found.length) setMessage("No se encontraron fuentes para esta pregunta. Ajusta los términos y vuelve a buscar.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudieron buscar las fuentes."); }
    finally { setBusy(false); }
  };
  const addCase = () => {
    if (!query.trim() || !answer.trim() || !author.trim() || !selectedIds.length) return;
    if (cases.some((item) => item.query.trim().toLocaleLowerCase() === query.trim().toLocaleLowerCase())) {
      setMessage("Esta pregunta ya está en el benchmark."); return;
    }
    const evidence = hits.filter((hit) => selectedIds.includes(hit.chunk_id)).map(({ note_id, note_path, section, chunk_id, source_reference }) => ({ note_id, note_path, section, chunk_id, source_reference }));
    if (!evidence.length) { setMessage("Selecciona al menos un fragmento encontrado."); return; }
    setCases((current) => [...current, { case_id: crypto.randomUUID(), query: query.trim(), reference_answer: { author_kind: "human", author: author.trim(), answer: answer.trim(), evidence } }]);
    setQuery(""); setAnswer(""); setHits([]); setSelectedIds([]); setMessage("Caso añadido. Puedes crear otro o registrar el benchmark.");
  };
  const save = async () => {
    if (!snapshot || !reviewer.trim() || !cases.length) return;
    setBusy(true); setMessage("");
    try {
      const record = await registerRealBenchmark({
        schema_version: "real-benchmark.v1", purpose: "external_validity", training_eligible: false,
        snapshot_hash: snapshot.artifact_sha256,
        human_review: { status: "approved", reviewer_kind: "human", reviewer: reviewer.trim() },
        cases,
      });
      onCreated(record); setCases([]);
      setMessage("Benchmark aprobado y registrado. Sus preguntas quedan excluidas de entrenamiento.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "No se pudo registrar el benchmark."); }
    finally { setBusy(false); }
  };
  return <fieldset className="wide-fieldset"><legend>Benchmark A · vault real</legend>
    <p>Escribe preguntas de evaluación, su respuesta de referencia humana y las fuentes que la respaldan. Las preguntas del benchmark no podrán usarse para entrenar.</p>
    <label><span>Snapshot completo</span><select value={snapshotId} onChange={(event) => { setSnapshotId(event.target.value); setIndexId(""); setCases([]); setHits([]); }}><option value="">Selecciona</option>{snapshots.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label>
    <label><span>Índice de ese snapshot</span><select value={indexId} onChange={(event) => { setIndexId(event.target.value); setHits([]); setSelectedIds([]); }}><option value="">Selecciona</option>{indexes.map((item) => <option key={item.record_id} value={item.record_id}>{item.title}</option>)}</select></label>
    <label><span>Pregunta de evaluación</span><textarea value={query} onChange={(event) => { setQuery(event.target.value); setHits([]); setSelectedIds([]); }} /></label>
    <button type="button" onClick={() => void search()} disabled={busy || !snapshotId || !indexId || !query.trim()}>Buscar fuentes</button>
    {hits.length ? <div className="manual-example-hits"><strong>Fragmentos encontrados</strong>{hits.map((hit) => <label key={hit.chunk_id}><input type="checkbox" checked={selectedIds.includes(hit.chunk_id)} onChange={() => setSelectedIds((current) => current.includes(hit.chunk_id) ? current.filter((id) => id !== hit.chunk_id) : [...current, hit.chunk_id])} /><span><strong>{hit.note_path} · {hit.section}</strong><small>{hit.content}</small></span></label>)}</div> : null}
    <label><span>Respuesta de referencia</span><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} /></label>
    <label><span>Autor de esta respuesta</span><input value={author} onChange={(event) => setAuthor(event.target.value)} /></label>
    <button type="button" onClick={addCase} disabled={busy || !answer.trim() || !author.trim() || selectedIds.length === 0}>Añadir caso</button>
    {cases.length ? <div className="benchmark-case-list"><strong>{cases.length} caso(s) listos</strong>{cases.map((item) => <div key={item.case_id}><span>{item.query} · {item.reference_answer.evidence.length} fuente(s)</span><button type="button" onClick={() => setCases((current) => current.filter((other) => other.case_id !== item.case_id))}>Quitar</button></div>)}</div> : null}
    <label><span>Persona que revisó y aprobó el benchmark</span><input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
    <button type="button" onClick={() => void save()} disabled={busy || !snapshot || !reviewer.trim() || !cases.length}>{busy ? "Trabajando…" : "Registrar benchmark aprobado"}</button>
    {message ? <p className="knowledge-message" role="status">{message}</p> : null}
  </fieldset>;
}
