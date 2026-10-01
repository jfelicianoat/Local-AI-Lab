import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/workspacePagination.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { mergeProductWorkspace } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const groups = ["knowledge", "benchmarks", "experiments", "reviews", "datasets", "training", "exports"];
const record = (id, rank) => ({ record_id: id, updated_at: String(rank).padStart(5, "0") });
const page = (items, total, hasMore, cursor = items.at(-1)) => ({
  schema_version: "local-ai-lab.workspace.v1", observed_at: "now",
  ...Object.fromEntries(groups.map((group) => [group, group === "experiments" ? items : []])),
  pagination: { experiments: { total, has_more: hasMore,
    cursor: cursor ? { updated_at: cursor.updated_at, record_id: cursor.record_id } : null } },
});

test("loading older pages preserves earlier results without duplicates", () => {
  const first = page([record("a", 3), record("b", 2)], 3, true);
  const older = page([record("b", 2), record("c", 1)], 3, false);
  const merged = mergeProductWorkspace(first, older, "more");
  assert.deepEqual(merged.experiments.map((item) => item.record_id), ["a", "b", "c"]);
  assert.equal(merged.pagination.experiments.has_more, false);
  assert.equal(first.experiments.length, 2);
});

test("periodic refresh keeps the cursor after an overlapping first page", () => {
  const current = page([record("a", 3), record("b", 2)], 4, true);
  const fresh = page([record("new", 4), record("a", 3)], 5, true);
  const merged = mergeProductWorkspace(current, fresh, "refresh");
  assert.deepEqual(merged.experiments.map((item) => item.record_id), ["new", "a", "b"]);
  assert.equal(merged.pagination.experiments.cursor.record_id, "b");
  assert.equal(merged.pagination.experiments.total, 5);
});

test("a nonoverlapping refresh restarts paging so a burst of new results is reachable", () => {
  const current = page([record("old-a", 3), record("old-b", 2)], 5, true);
  const fresh = page([record("new-a", 6), record("new-b", 5)], 7, true);
  const merged = mergeProductWorkspace(current, fresh, "refresh");
  assert.equal(merged.pagination.experiments.cursor.record_id, "new-b");
  assert.equal(merged.pagination.experiments.has_more, true);
});

test("a fully loaded history stays complete after refreshing its first page", () => {
  const current = page([record("a", 3), record("b", 2), record("c", 1)], 3, false);
  const fresh = page([record("a", 3), record("b", 2)], 3, true);
  const merged = mergeProductWorkspace(current, fresh, "refresh");
  assert.equal(merged.pagination.experiments.has_more, false);
  assert.equal(merged.experiments.length, 3);
});
