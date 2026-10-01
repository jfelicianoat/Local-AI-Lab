import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Rendering only: these checks do not attest native interaction.
const directory = new URL("../.test-tmp/export-panel/", import.meta.url);
await mkdir(directory, { recursive: true });
const bundle = new URL("export.cjs", directory);
await build({ entryPoints: [fileURLToPath(new URL("../src/ExportPanel.tsx", import.meta.url))],
  outfile: fileURLToPath(bundle), bundle: true, platform: "node", format: "cjs", jsx: "automatic",
  external: ["react", "react/jsx-runtime", "lucide-react"], logLevel: "silent" });
const { ExportPanel } = createRequire(import.meta.url)(fileURLToPath(bundle));

test("an untested export offers an initial verification and explains its cost", () => {
  const markup = renderToStaticMarkup(createElement(ExportPanel, { records: [{
    record_id: "trained", category: "training", title: "Modelo", status: "TRAINING_SUCCEEDED",
    artifact_sha256: "a".repeat(64), summary: {}, updated_at: "2026-10-01T00:00:00Z",
  }], nodes: [{ node_id: "worker", hostname: "Equipo", status: "online", capabilities_observed: true,
    last_heartbeat_at: "2026-10-01T00:00:00Z", tested_workloads: [] }], onChanged() {} }));
  assert.match(markup, /Comprobar y crear primer paquete/);
  assert.match(markup, /Falta comprobar Adaptador LoRA/);
  assert.match(markup, /disabled=""[^>]*>Crear paquete exportable/);
  assert.match(markup, /Puede tardar y necesitar mucha memoria/);
  assert.doesNotMatch(markup, /heartbeat|Nodo con conversión probada/);
});

test("empty or historical data and offline Workers explain missing prerequisites", () => {
  const markup = renderToStaticMarkup(createElement(ExportPanel, { records: [{
    record_id: "old", category: "training", title: "Anterior", status: "RESULT_REQUIRES_VALIDATION",
    artifact_sha256: "a".repeat(64), summary: {}, updated_at: "2026-10-01T00:00:00Z",
  }], nodes: [{ node_id: "offline", hostname: "Equipo desconectado", status: "offline", capabilities_observed: true,
    last_heartbeat_at: "2026-10-01T00:00:00Z", tested_workloads: ["export.adapter"] }], onChanged() {} }));
  assert.match(markup, /Completa primero un entrenamiento/);
  assert.match(markup, /Conecta un Worker/);
  assert.doesNotMatch(markup, /<option[^>]*>Anterior|<option[^>]*>Equipo desconectado/);
});
