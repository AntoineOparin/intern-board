// Match scores: the status shared by the board (badges, Best match note) and the Profile panel.
import * as api from "../api";
import type { RankingStatus } from "../types";

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
