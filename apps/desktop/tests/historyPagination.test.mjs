import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/historyPagination.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { mergeHistoryPage } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const item = (id, rank) => ({ job_id: id, updated_at: String(rank).padStart(5, "0") });
const page = (items, total, hasMore) => ({ items, pagination: {
  total, has_more: hasMore,
  cursor: items.length ? { id: items.at(-1).job_id, updated_at: items.at(-1).updated_at } : null,
} });

test("older job pages merge without duplicates", () => {
  const first = page([item("a", 3), item("b", 2)], 3, true);
  const older = page([item("b", 2), item("c", 1)], 3, false);
  const merged = mergeHistoryPage(first, older, "more", "job_id");
  assert.deepEqual(merged.items.map((record) => record.job_id), ["a", "b", "c"]);
  assert.equal(merged.pagination.has_more, false);
});

test("refresh keeps the older cursor when pages overlap", () => {
  const first = page([item("a", 3), item("b", 2)], 4, true);
  const fresh = page([item("new", 4), item("a", 3)], 5, true);
  const merged = mergeHistoryPage(first, fresh, "refresh", "job_id");
  assert.deepEqual(merged.items.map((record) => record.job_id), ["new", "a", "b"]);
  assert.equal(merged.pagination.cursor.id, "b");
});

test("a burst of new jobs restarts paging and keeps loaded history", () => {
  const first = page([item("a", 3), item("b", 2)], 5, true);
  const fresh = page([item("new-a", 6), item("new-b", 5)], 7, true);
  const merged = mergeHistoryPage(first, fresh, "refresh", "job_id");
  assert.equal(merged.pagination.cursor.id, "new-b");
  assert.deepEqual(merged.items.map((record) => record.job_id), ["new-a", "new-b", "a", "b"]);
});
