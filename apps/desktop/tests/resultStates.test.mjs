import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Static rendering verifies the state text and available actions, not native interaction.
const directory = new URL("../.test-tmp/result-states/", import.meta.url);
await mkdir(directory, { recursive: true });
const bundle = new URL("overview.cjs", directory);
await build({ entryPoints: [fileURLToPath(new URL("../src/overview.tsx", import.meta.url))],
  outfile: fileURLToPath(bundle), bundle: true, platform: "node", format: "cjs", jsx: "automatic",
  external: ["react", "react/jsx-runtime", "lucide-react"], logLevel: "silent" });
const { RecordBoard, NodeTable } = createRequire(import.meta.url)(fileURLToPath(bundle));

test("historical exports explain the missing proof and keep the save action", () => {
  const markup = renderToStaticMarkup(createElement(RecordBoard, { records: [{
    record_id: "old-export", category: "export", title: "Anterior", status: "RESULT_REQUIRES_VALIDATION",
    artifact_sha256: "a".repeat(64), summary: {}, updated_at: "2026-10-01T00:00:00Z",
  }], emptyTitle: "Vacío", emptyText: "Sin datos" }));
  assert.match(markup, /Resultado anterior pendiente de validación/);
  assert.match(markup, /no autoriza nuevos trabajos/);
  assert.match(markup, /Guardar paquete/);
  assert.doesNotMatch(markup, /RESULT_REQUIRES_VALIDATION/);
});

test("a Worker with invalidated proof shows the next required action", () => {
  const markup = renderToStaticMarkup(createElement(NodeTable, { nodes: [{
    node_id: "worker", hostname: "Equipo", status: "online", last_heartbeat_at: "2026-10-01T00:00:00Z",
    capabilities_observed: true, tested_workloads: [], capability_warning: "Repite el preflight antes de entrenar.",
  }] }));
  assert.match(markup, /DETECTADAS/);
  assert.match(markup, /role="status"[^>]*>Repite el preflight antes de entrenar/);
  assert.doesNotMatch(markup, /PROBADAS/);
});
