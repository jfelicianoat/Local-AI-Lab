import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/reviewDraft.ts", import.meta.url), "utf8");
const moduleText = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { newReviewDraft, editReviewDraft, reconcileReviewDraft } = await import(`data:text/javascript;base64,${Buffer.from(moduleText).toString("base64")}`);

test("a periodic refresh retains an unfinished human correction", () => {
  const saved = '{"answer":"Original"}';
  const edited = editReviewDraft(newReviewDraft("review-a", saved, 1), '{"answer":"Corrección humana"}');
  const refreshed = reconcileReviewDraft(edited, "review-a", saved, 1);
  assert.equal(refreshed.text, edited.text);
  assert.equal(refreshed.conflict, false);
});

test("an external update preserves the correction and exposes a conflict", () => {
  const edited = editReviewDraft(newReviewDraft("review-a", '{"answer":"Original"}', 1), '{"answer":"Corrección local"}');
  const remote = '{"answer":"Otra corrección guardada"}';
  const conflicted = reconcileReviewDraft(edited, "review-a", remote, 2);
  const polled = reconcileReviewDraft(conflicted, "review-a", remote, 2);
  assert.equal(polled.text, edited.text);
  assert.equal(polled.savedText, remote);
  assert.equal(polled.conflict, true);
  assert.deepEqual(newReviewDraft("review-a", polled.savedText, 2), { reviewId: "review-a", text: remote, savedText: remote, savedRevision: 2, conflict: false });
});

test("the Coordinator acknowledging our correction clears the unsaved state", () => {
  const edited = editReviewDraft(newReviewDraft("review-a", '{"answer":"Original"}', 1), '{"answer":"Corrección guardada"}');
  const acknowledged = reconcileReviewDraft(edited, "review-a", edited.text, 2);
  assert.equal(acknowledged.text, acknowledged.savedText);
  assert.equal(acknowledged.conflict, false);
});

test("clean drafts receive updates and opening a different review loads its content", () => {
  const initial = newReviewDraft("review-a", '{"answer":"A"}', 1);
  const updated = reconcileReviewDraft(initial, "review-a", '{"answer":"A actualizada"}', 2);
  assert.equal(updated.text, updated.savedText);
  const other = reconcileReviewDraft(editReviewDraft(updated, "Edición A"), "review-b", '{"answer":"B"}', 1);
  assert.equal(other.reviewId, "review-b");
  assert.equal(other.text, '{"answer":"B"}');
  assert.equal(other.conflict, false);
});

test("a revision change preserves edits even if the saved text did not change", () => {
  const saved = '{"answer":"Original"}';
  const edited = editReviewDraft(newReviewDraft("review-a", saved, 1), '{"answer":"Corrección humana"}');
  const refreshed = reconcileReviewDraft(edited, "review-a", saved, 3);
  assert.equal(refreshed.text, edited.text);
  assert.equal(refreshed.savedRevision, 3);
  assert.equal(refreshed.conflict, true);
});
