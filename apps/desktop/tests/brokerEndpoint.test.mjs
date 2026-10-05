import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const directory = new URL("../.test-tmp/broker-endpoint/", import.meta.url);
await mkdir(directory, { recursive: true });
const bundle = new URL("panels.cjs", directory);
await build({
  stdin: { contents: 'export * from "./experiments"; export { DistillationPanel } from "./datasets"; export { setBrokerEndpoint } from "./brokerEndpoint";',
    resolveDir: fileURLToPath(new URL("../src/", import.meta.url)), loader: "tsx" },
  outfile: fileURLToPath(bundle), bundle: true, platform: "node", format: "cjs", jsx: "automatic",
  external: ["react", "react/jsx-runtime"], define: { __APP_VERSION__: '"test"' }, logLevel: "silent",
});
const panels = createRequire(import.meta.url)(fileURLToPath(bundle));
const preferenceKey = "local-ai-lab.broker-endpoint.v1";
const pcEndpoint = "http://192.168.1.52:8765";
const stored = new Map();
globalThis.window = Object.assign(new EventTarget(), {
  localStorage: {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
  },
});
const props = { records: [], experiments: [], training: [], nodes: [], datasets: [], preflights: [],
  selection: {}, onCreated() {}, onChanged() {}, onSelectionChange() {} };
const markup = (name) => renderToStaticMarkup(createElement(panels[name], props));

test("fresh Broker settings point to the PC IA instead of this computer", () => {
  stored.clear();
  const html = markup("BrokerCompatibilityPanel");
  assert.ok(html.includes(`value="${pcEndpoint}"`), html);
  assert.match(html, /Dirección de AI Broker/);
  assert.doesNotMatch(html, /127\.0\.0\.1:8000|Endpoint local/);
});

test("Broker settings retain the saved endpoint when reopened", () => {
  const changedEndpoint = "http://192.168.1.77:8765";
  stored.set(preferenceKey, changedEndpoint);
  for (let opening = 0; opening < 2; opening += 1) {
    assert.ok(markup("BrokerCompatibilityPanel").includes(`value="${changedEndpoint}"`));
  }
});

test("Broker-dependent execution panels use the same saved address", () => {
  stored.set(preferenceKey, pcEndpoint);
  for (const panel of ["AgentExperimentPanel", "StrategyRunnerPanel", "DistillationPanel"]) {
    assert.ok(markup(panel).includes(`value="${pcEndpoint}"`), panel);
  }
});

test("editing the shared address persists it for settings and execution", () => {
  const changedEndpoint = "http://192.168.1.78:8765";
  panels.setBrokerEndpoint(changedEndpoint);
  assert.equal(stored.get(preferenceKey), changedEndpoint);
  for (const panel of ["BrokerCompatibilityPanel", "AgentExperimentPanel", "StrategyRunnerPanel", "DistillationPanel"]) {
    assert.ok(markup(panel).includes(`value="${changedEndpoint}"`), panel);
  }
  assert.deepEqual([...stored.keys()], [preferenceKey]);
});

test("clearing the endpoint does not silently restore a default destination", () => {
  panels.setBrokerEndpoint("");
  const html = markup("BrokerCompatibilityPanel");
  assert.doesNotMatch(html, /192\.168\.1\.52|127\.0\.0\.1:8000/);
  assert.match(html, /<button disabled="">Consultar health/);
});
