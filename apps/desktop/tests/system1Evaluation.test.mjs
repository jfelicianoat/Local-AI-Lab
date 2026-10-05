import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const directory = new URL("../.test-tmp/system1/", import.meta.url);
await mkdir(directory, { recursive: true });
const bundle = new URL("system1.cjs", directory);
await build({ entryPoints: [fileURLToPath(new URL("../src/System1EvaluationPanel.tsx", import.meta.url))],
  outfile: fileURLToPath(bundle), bundle: true, platform: "node", format: "cjs", jsx: "automatic",
  external: ["react", "react/jsx-runtime"], logLevel: "silent" });
const { defaultEvaluation, System1EvaluationPanel, System1Metrics } = createRequire(import.meta.url)(fileURLToPath(bundle));

test("evaluation is off by default and enabled policy explains calibration and fallback", () => {
  assert.equal(defaultEvaluation.enabled, false);
  assert.equal(defaultEvaluation.shadow_mode, true);
  const markup = renderToStaticMarkup(createElement(System1EvaluationPanel, {
    value: { ...defaultEvaluation, enabled: true }, onChange() {},
  }));
  assert.match(markup, /Comparar en sombra/);
  assert.match(markup, /Sin juez configurado/);
  assert.match(markup, /puntuaciones sin calibrar/);
  assert.match(markup, /Selección y fallback del Broker/);
});

test("metrics distinguish routes and show absent gold and cost as unmeasured", () => {
  const markup = renderToStaticMarkup(createElement(System1Metrics, { record: { summary: {
    evaluation: { shadow_mode: false }, evaluation_metrics: {
      total: 120, rates: { deterministic: 1 / 3, system1: 1 / 3, strong_judge: 1 / 3, previous_flow: 0 },
      escalation_rate: 1 / 3, system1_eligible_gold: { agreement: null, compared: 0 },
      shadow_vs_strong_judge: { agreement: null, compared: 0 },
    },
  } } }));
  assert.match(markup, /System 1 33.3 %/);
  assert.match(markup, /Juez 33.3 %/);
  assert.match(markup, /gold Sin medir/);
  assert.match(markup, /Coste de evaluación sin medir/);
});
