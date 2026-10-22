// Match scores: the status shared by the board (badges, Best match note) and the Profile panel.
import * as api from "../api";
import { loadListings } from "./board.svelte";
import type { JobStatus, RankResult, RankingStatus } from "../types";

export const STRONG = 70, OK = 45; // keep in step with the board's "Best match" groups
export type Tier = "strong" | "ok" | "weak";
export const tier = (score: number): Tier => (score >= STRONG ? "strong" : score >= OK ? "ok" : "weak");
export const TIER_LABEL: Record<Tier, string> = { strong: "Strong match", ok: "Possible match", weak: "Weak match" };

export const ranking = $state({ status: null as RankingStatus | null });

/** Also fills in keyword scores for any listings that don't have one yet (server side). */
export async function refreshStatus(): Promise<RankingStatus | null> {
  try { ranking.status = await api.rankingStatus({ quiet: true }); } catch { return null; }
  return ranking.status;
}

// ---------- Profile -> Ranking panel actions ----------

export const rankRun = $state({
  running: null as null | { seconds: number; status: JobStatus | "queued" },
  msg: { text: "", kind: "" },
});

export const progressText = (r: { seconds: number; status: string }) =>
  r.status === "queued" ? `Waiting to start… ${r.seconds}s` : `Claude is ranking listings… ${r.seconds}s`;

/** Claude rescores the 40 best keyword matches it hasn't scored yet. Runs only from a click. */
export async function rankWithClaude() {
  if (rankRun.running) return;
  rankRun.running = { seconds: 0, status: "queued" };
  rankRun.msg = { text: "", kind: "" };
  try {
    const r = await api.runJob<RankResult>("rank_listings", { limit: 40 }, (seconds, status) => {
      rankRun.running = { seconds, status };
      rankRun.msg = { text: progressText(rankRun.running), kind: "busy" };
    });
    rankRun.running = null;
    await refreshStatus();
    let text = r.message || `Ranked ${r.ranked} listing${r.ranked === 1 ? "" : "s"} in ${Math.round(r.seconds)}s.`;
    if (r.failed_batches) text += ` ${r.skipped} couldn't be ranked: ${r.error}`;
    rankRun.msg = { text, kind: r.failed_batches ? "error" : "ok" };
    loadListings(true);
  } catch (err) {
    rankRun.running = null;
    rankRun.msg = { text: (err as Error).message, kind: "error" };
  }
}

export async function recomputeQuick() {
  rankRun.msg = { text: "Scoring…", kind: "busy" };
  try {
    const r = await api.rankQuick({ quiet: true });
    ranking.status = r.status;
    rankRun.msg = { text: `Scored ${r.computed.toLocaleString()} listings in ${r.seconds}s.`, kind: "ok" };
    loadListings(true);
  } catch (err) {
    rankRun.msg = { text: (err as Error).message, kind: "error" };
  }
}

/** If the page was closed mid-ranking, follow the job that is still going. */
export async function followRunningJob(jobId: string) {
  if (rankRun.running) return;
  rankRun.running = { seconds: 0, status: "running" };
  const started = Date.now();
  for (;;) {
    await new Promise(r => setTimeout(r, 2000));
    let job;
    try { job = await api.job(jobId, { quiet: true }); } catch { break; }
    rankRun.running = { seconds: Math.round((Date.now() - started) / 1000), status: job.status };
    rankRun.msg = { text: progressText(rankRun.running), kind: "busy" };
    if (job.status === "done" || job.status === "error") break;
  }
  rankRun.running = null;
  rankRun.msg = { text: "", kind: "" };
  await refreshStatus();
  loadListings(true);
}
