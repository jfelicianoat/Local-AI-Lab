import type { HistoryPage } from "./contracts";

export function mergeHistoryPage<T extends { updated_at: string }>(
  current: HistoryPage<T>, incoming: HistoryPage<T>,
  mode: "refresh" | "more", identity: keyof T,
): HistoryPage<T> {
  const byId = new Map(current.items.map((item) => [String(item[identity]), item]));
  const overlaps = incoming.items.some((item) => byId.has(String(item[identity])));
  for (const item of incoming.items) {
    const id = String(item[identity]);
    const previous = byId.get(id);
    if (!previous || item.updated_at >= previous.updated_at) byId.set(id, item);
  }
  const items = [...byId.values()].sort((left, right) =>
    right.updated_at.localeCompare(left.updated_at) ||
    String(left[identity]).localeCompare(String(right[identity])));
  let pagination = incoming.pagination;
  if (mode === "refresh" && items.length >= incoming.pagination.total) {
    pagination = { ...incoming.pagination, has_more: false,
      cursor: current.pagination.cursor ?? incoming.pagination.cursor };
  } else if (mode === "refresh" && overlaps && current.pagination.has_more) {
    pagination = { ...incoming.pagination, has_more: true, cursor: current.pagination.cursor };
  }
  return { items, pagination };
}
