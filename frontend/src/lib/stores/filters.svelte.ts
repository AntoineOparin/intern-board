// The board's filters, saved under the `filters` storage key (same shape as the old app).
import { load, store } from "../storage";
import type { Region, Sort, Source } from "../types";

export interface Filters {
  q: string;
  region: Region | "";
  category: string;
  term: string;
  degree: string;
  source: Source | "";
  sort: Sort;
  new_only: boolean;
  hide_tracked: boolean;
}

export const filters = $state<Filters>({
  q: "", region: "", category: "", term: "", degree: "", source: "", sort: "posted", new_only: false, hide_tracked: false,
});

export function restoreFilters() {
  const saved = load<Partial<Filters>>("filters", {});
  for (const [k, v] of Object.entries(saved)) {
    if (k in filters && typeof v === typeof filters[k as keyof Filters]) (filters as unknown as Record<string, unknown>)[k] = v;
  }
}

export const saveFilters = () => store("filters", { ...filters });

export const anyActive = () =>
  !!(filters.q.trim() || filters.region || filters.category || filters.term || filters.degree || filters.source || filters.new_only || filters.hide_tracked);

export function clearFilterValues() {
  Object.assign(filters, { q: "", region: "", category: "", term: "", degree: "", source: "", new_only: false, hide_tracked: false });
}
