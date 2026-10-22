import { credits, ready } from "../../lib/stores/credits.svelte";

export const shortDate = (iso: string | null | undefined) =>
  iso ? new Date(String(iso).slice(0, 10) + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
export const dayDate = (ts: number | null | undefined) =>
  ts ? new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
export const renewText = () => {
  const a = credits.account;
  return ready(a) && a.renews ? `renews ${shortDate(a.renews)}` : "renews monthly";
};
