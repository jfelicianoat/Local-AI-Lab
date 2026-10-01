import type { ProductWorkspace, WorkspaceGroup } from "./contracts";

export const workspaceGroups: WorkspaceGroup[] = [
  "knowledge", "benchmarks", "experiments", "reviews", "datasets", "training", "exports",
];

export function mergeProductWorkspace(
  current: ProductWorkspace, incoming: ProductWorkspace, mode: "refresh" | "more",
): ProductWorkspace {
  if (!current.pagination || !incoming.pagination) return incoming;
  const merged: ProductWorkspace = { ...current, observed_at: incoming.observed_at, pagination: { ...current.pagination } };
  for (const group of workspaceGroups) {
    const byId = new Map(current[group].map((item) => [item.record_id, item]));
    const overlapsCurrentHead = incoming[group].some((item) => byId.has(item.record_id));
    for (const item of incoming[group]) {
      const previous = byId.get(item.record_id);
      if (!previous || item.updated_at >= previous.updated_at) byId.set(item.record_id, item);
    }
    merged[group] = [...byId.values()].sort((left, right) =>
      right.updated_at.localeCompare(left.updated_at) || left.record_id.localeCompare(right.record_id));
    const nextPage = incoming.pagination[group];
    const previousPage = current.pagination[group];
    if (!nextPage) continue;
    merged.pagination![group] = mode === "refresh" && merged[group].length >= nextPage.total
      ? { ...nextPage, has_more: false, cursor: previousPage?.cursor ?? nextPage.cursor }
      : mode === "refresh" && !overlapsCurrentHead && current[group].length > 0 && nextPage.has_more
        ? nextPage
      : mode === "refresh" && previousPage?.has_more
        ? { ...nextPage, has_more: true, cursor: previousPage.cursor }
        : nextPage;
  }
  return merged;
}
