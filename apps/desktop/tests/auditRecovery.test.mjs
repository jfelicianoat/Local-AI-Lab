import assert from "node:assert/strict";
import test from "node:test";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const directory = new URL("../.test-tmp/audit-recovery/", import.meta.url);
await mkdir(directory, { recursive: true });
async function module(name) {
  const target = new URL(`${name}.cjs`, directory);
  await build({ entryPoints: [fileURLToPath(new URL(`../src/${name}.ts`, import.meta.url))],
    outfile: fileURLToPath(target), bundle: true, platform: "node", format: "cjs", logLevel: "silent" });
  return createRequire(import.meta.url)(fileURLToPath(target));
}
const { readMissionDraft, writeMissionDraft, sameMissionFields, missionFields,
  readSelectedMission, selectMission, missionStorage, resolveMissionSelection } = await module("missionDraft");
const { LatestRequest } = await module("latestRequest");
const fields = { strategy: "rag", task: "Comparar Atlas", success: "90 %", constraints: "local",
  teacherSource: "broker", teacherModel: "", studentModel: "" };
function storage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key) };
}
test("a new mission survives navigation and reopening before its first remote save", () => {
  const local = storage();
  const original = { missionId: null, expectedRevision: 0, fields, base: null };
  assert.equal(writeMissionDraft(local, original), true);
  assert.deepEqual(readMissionDraft(local, null), original);
  assert.equal(sameMissionFields(fields, null), false);
});
test("offline drafts remain separate and preserve the revision against which they were edited", () => {
  const local = storage();
  for (const id of ["first", "second"]) writeMissionDraft(local, { missionId: id,
    expectedRevision: 3, fields: { ...fields, task: id }, base: fields });
  assert.equal(readMissionDraft(local, "first").fields.task, "first");
  assert.equal(readMissionDraft(local, "second").expectedRevision, 3);
  assert.equal(readMissionDraft(local, null), null);
});
test("failed local persistence is explicit and malformed recovery cannot replace a plan", () => {
  assert.equal(writeMissionDraft({ setItem() { throw new Error("quota"); } }, {}), false);
  assert.equal(readMissionDraft({ getItem() { return '{"fields": {}}'; } }, null), null);
  assert.equal(readMissionDraft({ getItem() { return 'broken'; } }, null), null);
});
test("restricted WebView storage cannot throw from reading or selecting a mission", () => {
  const originalWindow = globalThis.window;
  globalThis.window = {};
  Object.defineProperty(globalThis.window, "localStorage", { get() { throw new Error("SecurityError"); } });
  try {
    const local = missionStorage();
    assert.equal(readSelectedMission(local), null);
    assert.equal(selectMission(local, "plan"), false);
    assert.equal(selectMission(local, null), false);
    assert.equal(readMissionDraft(local, null), null);
    assert.equal(writeMissionDraft(local, { missionId: null, fields }), false);
  } finally { globalThis.window = originalWindow; }
});
test("selecting a saved plan leaves the new draft available for explicit recovery", () => {
  const local = storage();
  const original = { missionId: null, expectedRevision: 0, fields, base: null };
  writeMissionDraft(local, original);
  selectMission(local, "saved-plan");
  assert.equal(readSelectedMission(local), "saved-plan");
  assert.deepEqual(readMissionDraft(local, null), original);
  selectMission(local, null);
  assert.deepEqual(readMissionDraft(local, readSelectedMission(local)), original);
});
test("a missing saved mission is not a writable identity and leaves independent drafts intact", () => {
  const local = storage();
  const first = { missionId: null, expectedRevision: 0, fields, base: null };
  const missing = { ...first, missionId: "missing", expectedRevision: 4,
    fields: { ...fields, task: "Recovered missing plan" } };
  writeMissionDraft(local, first); writeMissionDraft(local, missing);
  const selection = resolveMissionSelection("missing", [{ mission_id: "available" }]);
  assert.deepEqual(selection, { missionId: null, missing: true });
  assert.equal(readMissionDraft(local, "missing").fields.task, "Recovered missing plan");
  assert.deepEqual(readMissionDraft(local, null), first);
  assert.deepEqual(resolveMissionSelection(null, []), { missionId: null, missing: false });
  assert.deepEqual(resolveMissionSelection("available", [{ mission_id: "available" }]),
    { missionId: "available", missing: false });
});
test("acknowledged normalization clears pending changes while subsequent edits remain dirty", () => {
  const saved = missionFields({ strategy: "rag", task: "Comparar Atlas", success: "90 %",
    constraints: "local", teacher_source: null, teacher_model: null, student_model: null });
  assert.equal(sameMissionFields({ ...fields, task: " Comparar Atlas " }, saved), true);
  assert.equal(sameMissionFields({ ...fields, task: "Texto editado durante el guardado" }, saved), false);
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
test("a late refresh cannot replace a newer successful observation", async () => {
  const gate = new LatestRequest(), older = deferred(), newer = deferred();
  const a = gate.run(() => older.promise), b = gate.run(() => newer.promise);
  newer.resolve("current");
  assert.deepEqual(await b, { status: "success", value: "current" });
  older.resolve("old");
  assert.deepEqual(await a, { status: "obsolete" });
});
test("a stale failure cannot mark a connected workspace as offline", async () => {
  const gate = new LatestRequest(), older = deferred();
  const a = gate.run(() => older.promise);
  assert.equal((await gate.run(async () => "current")).status, "success");
  older.reject(new Error("old failure"));
  assert.deepEqual(await a, { status: "obsolete" });
});
test("a current failure is recoverable and unmounted requests are invalidated", async () => {
  const gate = new LatestRequest(), pending = deferred();
  const failure = await gate.run(async () => { throw new Error("offline"); });
  assert.equal(failure.status, "failure");
  const request = gate.run(() => pending.promise);
  gate.invalidate(); pending.resolve("late");
  assert.deepEqual(await request, { status: "obsolete" });
  assert.equal((await gate.run(async () => "reconnected")).value, "reconnected");
});
test("background polls coalesce while a slow observation can still finish", async () => {
  const gate = new LatestRequest(), pending = deferred();
  const first = gate.run(() => pending.promise);
  let duplicateLoads = 0;
  for (let interval = 0; interval < 3; interval++) {
    assert.deepEqual(await gate.run(async () => { duplicateLoads++; return "duplicate"; },
      { background: true }), { status: "obsolete" });
  }
  pending.resolve("slow but current");
  assert.equal((await first).value, "slow but current");
  assert.equal(duplicateLoads, 0);
  assert.equal((await gate.run(async () => "next", { background: true })).value, "next");
});
test("acknowledging a mutation prevents an earlier observation restoring the old revision", async () => {
  const gate = new LatestRequest(), pending = deferred();
  const earlier = gate.run(() => pending.promise);
  const saved = { mission_id: "one", revision: 2, task: "Current work" };
  gate.invalidate();
  pending.resolve({ ...saved, revision: 1, task: "Old work" });
  assert.deepEqual(await earlier, { status: "obsolete" });
  assert.equal((await gate.run(async () => saved)).value.revision, 2);
});
