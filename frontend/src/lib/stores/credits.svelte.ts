// Prospeo credits, shared by Find People and Profile -> Integrations.
import * as api from "../api";
import type { ProspeoAccount } from "../types";

export const credits = $state({ account: null as ProspeoAccount | null });

type Ready = Extract<ProspeoAccount, { masked: string }>;
export const ready = (a: ProspeoAccount | null): a is Ready => !!a && a.configured && !a.error;
export const noCredits = () => ready(credits.account) && credits.account.empty;

export async function loadCredits() {
  try { credits.account = await api.prospeo({ quiet: true }); } catch { credits.account = null; }
  return credits.account;
}
