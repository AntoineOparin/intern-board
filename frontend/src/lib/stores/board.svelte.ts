// The internship board: listings for the current filters, page by page, and the counts around them.
import { SvelteSet } from "svelte/reactivity";
import * as api from "../api";
import { filters, saveFilters, clearFilterValues } from "./filters.svelte";
import { ranking, refreshStatus } from "./ranking.svelte";
import { meta, loadMeta } from "./meta.svelte";
import { toast } from "./toast.svelte";
import type { Listing, Sort } from "../types";

export const PAGE = 50;

/** Listings whose match reason is shown under the row. */
export const why = new SvelteSet<string>();

export const board = $state({
  items: [] as Listing[],
  total: 0,
  loading: false, // a reset is loading: show the skeleton
  loaded: false,
  prevVisit: 0, // the "new since last visit" baseline
  newCount: null as number | null,
  refreshing: false,
  refreshResult: { text: "", cls: "muted" },
  syncOverride: null as null | { kind: string; text: string },
});

let token = 0;
let loadingMore = false;

function query(offset: number) {
  const f = filters;
  return {
    offset, limit: PAGE, sort: f.sort,
    q: f.q.trim() || undefined, region: f.region || undefined, category: f.category || undefined, term: f.term || undefined,
    degree: f.degree || undefined, source: f.source || undefined,
    since: f.new_only ? board.prevVisit : undefined, hide_tracked: f.hide_tracked || undefined,
  };
}

export async function loadListings(reset: boolean) {
  const mine = ++token;
  const offset = reset ? 0 : board.items.length;
  if (reset) board.loading = true;
  let data;
  try {
    data = await api.listings(query(offset));
  } catch {
    if (reset && mine === token) { board.items = []; board.loading = false; }
    return;
  }
  if (mine !== token) return; // a newer filter change won
  board.items = reset ? data.items : [...board.items, ...data.items];
  if (reset) why.clear();
  board.total = data.total;
  board.loading = false;
  board.loaded = true;
  listingsLoaded();
}

export async function loadMore() {
  if (loadingMore || board.items.length >= board.total) return;
  loadingMore = true;
  try { await loadListings(false); } finally { loadingMore = false; }
}

export function filtersChanged() {
  saveFilters();
  loadListings(true);
}

export function clearFilters() {
  clearFilterValues();
  filtersChanged();
}

export async function updateNewCount() {
  const { total } = await api.listings({ limit: 1, since: board.prevVisit });
  board.newCount = total;
}

// New listings since the last check have no score yet; fill them in once, then redraw.
let filling = false;
function listingsLoaded() {
  if (filters.sort !== "match" || filling || !ranking.status?.has_profile) return;
  if (!board.items.some(l => l.match_score == null)) return;
  filling = true;
  refreshStatus().then(s => { if (s?.computed) loadListings(true); }).finally(() => { filling = false; });
}

/** Group label for a listing under the current sort. */
export function groupKey(l: Listing, sort: Sort, dayGroup: (ts: number | null) => string): string {
  if (sort === "posted") return dayGroup(l.date_posted);
  if (sort === "added") return dayGroup(l.first_seen);
  if (sort === "match") return l.match_score == null ? "Not scored" : l.match_score >= 70 ? "Strong match" : l.match_score >= 45 ? "Possible match" : "Weak match";
  return (l.company[0] || "#").toUpperCase().replace(/[^A-Z]/, "#");
}

const WAIT_POLL_MS = 2000;
const WAIT_LIMIT_MS = 5 * 60 * 1000;

/** Wait for a refresh the server is already running (hourly or at startup) to finish.
 *  It's done when the last refresh time or the last error changes. */
async function waitForRunningRefresh(before: { last_refresh: number; last_error: string }) {
  const started = Date.now();
  while (Date.now() - started < WAIT_LIMIT_MS) {
    await new Promise(r => setTimeout(r, WAIT_POLL_MS));
    let m;
    try { m = await api.meta(); } catch { continue; }
    if (m.last_refresh !== before.last_refresh) return { done: true as const, error: "" };
    if (m.last_error && m.last_error !== before.last_error) return { done: true as const, error: m.last_error };
  }
  return { done: false as const, error: "" };
}

export async function refreshNow(reloadCompanies?: () => Promise<unknown>) {
  board.refreshing = true;
  const before = { last_refresh: meta.data?.last_refresh ?? 0, last_error: meta.data?.last_error ?? "" };
  board.refreshResult = { text: "Checking every source, about 30–60 seconds.", cls: "muted" };
  board.syncOverride = { kind: "busy", text: "Checking sources…" };
  try {
    const r = await api.refresh();
    if (r.status === "ok") {
      board.refreshResult = r.new
        ? { text: `${r.new.toLocaleString()} new internship${r.new === 1 ? "" : "s"}`, cls: "ok" }
        : { text: "No new internships since the last check.", cls: "muted" };
    } else if (r.status === "already_running") {
      // Keep spinning until the server's own refresh finishes, then show what it found.
      board.refreshResult = { text: "Another refresh is already running. Waiting for it to finish…", cls: "muted" };
      const w = await waitForRunningRefresh(before);
      if (w.error) {
        board.refreshResult = { text: "", cls: "muted" };
        toast(`Refresh failed: ${w.error}`);
      } else {
        board.refreshResult = w.done
          ? { text: "Refresh finished. The board is up to date.", cls: "ok" }
          : { text: "The refresh is taking longer than usual. The board updates when it finishes.", cls: "muted" };
      }
    } else {
      board.refreshResult = { text: "", cls: "muted" };
      toast(`Refresh failed: ${r.error}`);
    }
    await Promise.all([loadMeta().finally(() => { board.syncOverride = null; }), loadListings(true), updateNewCount(), reloadCompanies?.()]);
  } catch {
    board.refreshResult = { text: "", cls: "muted" };
    await loadMeta().catch(() => {});
  } finally {
    board.syncOverride = null;
    board.refreshing = false;
    setTimeout(() => { if (!board.refreshing) board.refreshResult = { text: "", cls: board.refreshResult.cls }; }, 20000);
  }
}
