import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import React, { act } from "react";

// Use an installed jsdom, or explicitly provide a compatible existing package.
// No dependency is downloaded, and the source application is not modified.
const require = createRequire(import.meta.url);
const { JSDOM } = require(process.env.LAL_TEST_JSDOM ?? "jsdom");
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>',
  { url: "http://local-ai-lab.test/" });
for (const key of ["window", "document", "HTMLElement", "HTMLInputElement", "HTMLTextAreaElement",
  "Event", "MouseEvent", "MutationObserver"]) globalThis[key] = dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import("react-dom/client");
const directory = new URL("../.test-tmp/workflows/", import.meta.url);
await mkdir(directory, { recursive: true });
const target = new URL("application.cjs", directory);
await build({ stdin: { contents: `export {default as App} from './App';
  export {ManualExamplePanel} from './knowledge';
  export {previewOverview,previewWorkspace} from './previewData';
  export {writeMissionDraft,readMissionDraft} from './missionDraft';`,
  resolveDir: fileURLToPath(new URL("../src/", import.meta.url)), loader: "tsx" },
  outfile: fileURLToPath(target), bundle: true, platform: "node", format: "cjs", jsx: "automatic",
  external: ["react", "react-dom", "react-dom/client", "react/jsx-runtime"],
  define: { __APP_VERSION__: '"0.1.8-test"', "import.meta.env.DEV": "false" },
  plugins: [{ name: "synthetic-tauri-transport", setup(builder) {
    builder.onResolve({ filter: /^@tauri-apps\/api\/core$/ }, () => ({ path: "test-transport", namespace: "synthetic" }));
    builder.onLoad({ filter: /.*/, namespace: "synthetic" }, () => ({
      contents: "export const invoke = (command, input) => globalThis.__lalInvoke(command, input);" }));
  }}], logLevel: "silent" });
const app = require(fileURLToPath(target));
let root, backend, confirms = [], confirmAnswer = true;
const container = document.getElementById("root");
const localStorageDescriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
const clone = (value) => structuredClone(value);
const makePlan = (id = "saved", task = "Plan guardado Atlas") => ({ mission_id: id,
  revision: 1, strategy: "prompting", task, success: "80 % de respuestas verificadas", constraints: "local",
  teacher_source: null, teacher_model: null, student_model: null, links: [],
  stage_states: ["configured", "not_started", "not_started", "not_started", "not_started"],
  resume_step: 0, created_at: "2026-11-19T12:00:00Z", updated_at: "2026-11-19T12:00:00Z" });
const fields = { strategy: "rag", task: "Borrador nuevo independiente", success: "90 %", constraints: "local",
  teacherSource: "broker", teacherModel: "", studentModel: "" };
function setup(plans = []) {
  window.localStorage.clear(); confirms = []; confirmAnswer = true;
  window.confirm = (text) => { confirms.push(text); return confirmAnswer; };
  backend = { missions: clone(plans), calls: [], failReads: false, failSaves: false, pending: {} };
  globalThis.__lalInvoke = async (command, input) => {
    backend.calls.push({ command, input: clone(input) });
    if (backend.pending[command]) return backend.pending[command].promise;
    if (backend.failReads && command.startsWith("load_")) throw new Error("Coordinator desconectado de prueba");
    if (command === "load_overview") return clone(app.previewOverview);
    if (command === "load_workspace") return clone(app.previewWorkspace);
    if (command === "load_reviews_page" || command === "load_jobs_page")
      return { items: [], pagination: { total: 0, has_more: false, cursor: null } };
    if (command === "load_missions") return clone(backend.missions);
    if (command === "save_mission") {
      if (backend.failSaves) throw new Error("Fallo de guardado de prueba");
      const old = backend.missions.find((p) => p.mission_id === input.missionId);
      if ((input.expectedRevision ?? 0) !== (old?.revision ?? 0)) throw new Error("Operación rechazada (409)");
      const saved = { ...(old ?? makePlan(input.missionId)), strategy: input.strategy,
        task: input.task.trim(), success: input.success.trim(), constraints: input.constraints.trim(),
        revision: (old?.revision ?? 0) + 1 };
      backend.missions = [saved, ...backend.missions.filter((p) => p.mission_id !== saved.mission_id)];
      return clone(saved);
    }
    throw new Error(`Unexpected test transport command: ${command}`);
  };
}
async function mount(element = React.createElement(app.App)) {
  root = createRoot(container);
  await act(async () => { root.render(element); });
}
async function click(text) {
  const button = [...container.querySelectorAll("button")].find((node) =>
    node.textContent.trim() === text || node.getAttribute("aria-label") === text || node.title === text);
  assert.ok(button, `Missing button: ${text}; ${container.textContent}`);
  assert.equal(button.disabled, false, `Disabled button: ${text}`);
  await act(async () => { button.click(); });
}
async function edit(textareaIndex, value) {
  const node = container.querySelectorAll("textarea")[textareaIndex];
  assert.ok(node, `Missing textarea ${textareaIndex}`);
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set.call(node, value);
    node.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}
async function unmount() {
  if (root) { await act(async () => root.unmount()); root = null; }
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function select(index, value) {
  const node = container.querySelectorAll("select")[index];
  assert.ok(node);
  await act(async () => { node.value = value; node.dispatchEvent(new window.Event("change", { bubbles: true })); });
}
afterEach(async () => {
  await unmount();
  Object.defineProperty(window, "localStorage", localStorageDescriptor);
});

test("mounted app preserves a new draft while loading a saved plan and recovers it after navigation", async () => {
  setup([makePlan()]);
  app.writeMissionDraft(window.localStorage, { missionId: null, expectedRevision: 0, fields, base: null });
  window.localStorage.setItem("local-ai-lab.selected-mission.v1", "saved");
  await mount();
  assert.equal(container.querySelector("textarea").value, "Plan guardado Atlas");
  assert.match(container.textContent, /Plan guardado en Coordinator/);
  assert.equal(app.readMissionDraft(window.localStorage, null).fields.task, fields.task);
  await click("Nueva misión");
  assert.equal(container.querySelector("textarea").value, fields.task);
  await click("Planes y borradores");
  const savedButton = [...container.querySelectorAll(".mission-saved-list button")][0];
  assert.ok(savedButton);
  await act(async () => savedButton.click());
  await click("Nueva misión");
  assert.equal(container.querySelector("textarea").value, fields.task);
  await unmount(); await mount();
  assert.equal(container.querySelector("textarea").value, fields.task);
});

test("missing selected mission permits a new plan and never recreates its old identity", async () => {
  setup(); window.localStorage.setItem("local-ai-lab.selected-mission.v1", "missing");
  await mount();
  assert.match(container.textContent, /ya no está en Coordinator/);
  await edit(0, "Tarea nueva tras restaurar"); await edit(1, "80 %");
  await click("Crear plan guiado");
  assert.equal(backend.missions.length, 1);
  assert.notEqual(backend.missions[0].mission_id, "missing");
  assert.equal(backend.missions[0].task, "Tarea nueva tras restaurar");
});

test("refresh failure retains the mounted editor and its unsaved text", async () => {
  setup(); await mount(); await edit(0, "Conservar mi texto");
  const editor = container.querySelector("textarea"); backend.failReads = true;
  await click("Actualizar");
  assert.equal(container.querySelector("textarea"), editor);
  assert.equal(editor.value, "Conservar mi texto");
  assert.match(container.textContent, /desconectado de prueba/);
});

test("unavailable localStorage cannot hide Coordinator plans or crash the app", async () => {
  setup([makePlan()]);
  Object.defineProperty(window, "localStorage", { configurable: true, get() { throw new Error("Storage denied"); } });
  await mount();
  assert.ok(container.querySelector("textarea"), container.textContent);
  assert.match(container.textContent, /borrador/i);
  await click("Planes y borradores");
  const saved = container.querySelector(".mission-saved-list button"); assert.ok(saved);
  await act(async () => saved.click());
  assert.equal(container.querySelector("textarea").value, "Plan guardado Atlas");
});

test("a second session exposes a conflict and copying preserves both its plan and our local text", async () => {
  setup([makePlan()]); window.localStorage.setItem("local-ai-lab.selected-mission.v1", "saved");
  app.writeMissionDraft(window.localStorage, { missionId: null, expectedRevision: 0, fields, base: null });
  await mount(); await edit(0, "Mi edición todavía sin guardar");
  backend.missions[0] = { ...backend.missions[0], revision: 2, task: "Trabajo de la otra sesión" };
  await click("Actualizar");
  assert.match(container.textContent, /Conflicto: borrador conservado/);
  assert.equal(container.querySelector("textarea").value, "Mi edición todavía sin guardar");
  await click("Crear copia con mi borrador");
  assert.equal(backend.missions.length, 2);
  assert.equal(backend.missions.find((p) => p.mission_id === "saved").task, "Trabajo de la otra sesión");
  assert.equal(backend.missions.find((p) => p.mission_id !== "saved").task, "Mi edición todavía sin guardar");
  assert.equal(app.readMissionDraft(window.localStorage, null).fields.task, fields.task);
});

test("changing strategy cannot silently replace a separate new draft", async () => {
  setup([makePlan()]); window.localStorage.setItem("local-ai-lab.selected-mission.v1", "saved");
  app.writeMissionDraft(window.localStorage, { missionId: null, expectedRevision: 0, fields, base: null });
  await mount();
  const strategy = [...container.querySelectorAll(".strategy-list button")].find((node) => node.textContent.includes("LoRA / SFT local"));
  confirmAnswer = false; await act(async () => strategy.click());
  assert.equal(container.querySelector("textarea").value, "Plan guardado Atlas");
  assert.equal(app.readMissionDraft(window.localStorage, null).fields.task, fields.task);
  assert.equal(confirms.length, 1);
  confirmAnswer = true; await act(async () => strategy.click());
  assert.equal(app.readMissionDraft(window.localStorage, null).fields.strategy, "lora");
  assert.equal(app.readMissionDraft(window.localStorage, null).fields.task, "Plan guardado Atlas");
});

test("failed save preserves edits across unmount and later retries successfully", async () => {
  setup([makePlan()]); window.localStorage.setItem("local-ai-lab.selected-mission.v1", "saved");
  await mount(); backend.failSaves = true; await edit(0, "Cambios durante desconexión");
  await click("Guardar plan");
  assert.match(container.textContent, /No se pudo guardar en Coordinator/);
  await unmount(); await mount();
  assert.equal(container.querySelector("textarea").value, "Cambios durante desconexión");
  backend.failSaves = false; await click("Guardar plan");
  assert.equal(backend.missions[0].task, "Cambios durante desconexión");
  assert.match(container.textContent, /Plan guardado en Coordinator/);
});

test("manual source lookup locks its context and a failed creation keeps the proposed answer", async () => {
  setup(); const lookup = deferred(), create = deferred();
  backend.pending.preview_manual_example = lookup;
  const records = [{ record_id: "snapshot", category: "snapshot", status: "COMPLETE", title: "Atlas", summary: {} },
    { record_id: "index", category: "index", status: "READY", title: "Índice Atlas", summary: { snapshot_id: "snapshot" } }];
  const created = [];
  await mount(React.createElement(app.ManualExamplePanel, { knowledge: records, onCreated: (review) => created.push(review) }));
  await select(0, "snapshot"); await select(1, "index");
  await edit(0, "¿Quién dirige Atlas?"); await edit(1, "Ana dirige Atlas");
  await click("Buscar fuentes");
  assert.equal(container.querySelector("fieldset").disabled, true);
  assert.ok([...container.querySelectorAll("input,textarea,select,button")].every((node) => node.matches(":disabled")));
  await act(async () => lookup.resolve([{ chunk_id: "chunk", note_path: "Equipo.md", section: "Atlas", content: "Ana dirige Atlas", score: 1 }]));
  assert.equal(container.querySelector("fieldset").disabled, false);
  const checkbox = container.querySelector('input[type="checkbox"]'); assert.ok(checkbox);
  await act(async () => checkbox.click());
  backend.pending.create_manual_example = create;
  await click("Crear borrador de revisión");
  assert.equal(container.querySelector("fieldset").disabled, true);
  await act(async () => create.reject(new Error("Error de persistencia de prueba")));
  assert.equal(container.querySelectorAll("textarea")[1].value, "Ana dirige Atlas");
  assert.match(container.textContent, /Error de persistencia de prueba/);
  const retry = deferred(); backend.pending.create_manual_example = retry;
  await click("Crear borrador de revisión");
  await act(async () => retry.resolve({ review_id: "manual", revision: 1, run_id: "manual",
    case_id: "manual", snapshot_id: "snapshot", reviewer: "desktop-user", status: "draft",
    training_state: "excluded", context: {}, original: {}, corrected: null,
    verification: null, diff_text: null, updated_at: "2026-11-19T12:00:00Z" }));
  assert.equal(created.length, 1);
  assert.equal(container.querySelectorAll("textarea")[1].value, "");
  assert.match(container.textContent, /Ejemplo creado como borrador/);
});
