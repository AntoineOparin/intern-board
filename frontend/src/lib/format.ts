// Formatting helpers shared by every page (ported from app.js).
export const DAY = 86400;

/** "just now", "5m ago", "3h ago", "12d ago", or "Mar 2026" for older. */
export function ago(ts: number | null | undefined): string {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < DAY) return `${Math.round(s / 3600)}h ago`;
  if (s < DAY * 60) return `${Math.round(s / DAY)}d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

/** Board date groups: Today, Yesterday, This week, This month, Older. */
export function dayGroup(ts: number | null | undefined): string {
  if (!ts) return "Date unknown";
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const today = start.getTime() / 1000;
  if (ts >= today) return "Today";
  if (ts >= today - DAY) return "Yesterday";
  if (ts >= today - 6 * DAY) return "This week";
  if (ts >= today - 30 * DAY) return "This month";
  return "Older";
}

/** Two-letter initials: "Acme Robotics" -> "AR", "Stripe" -> "ST". */
export function monogram(name: string | null | undefined): string {
  const words = String(name ?? "").replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] ?? "?") + (words.length > 1 ? words[1][0] : words[0]?.[1] ?? "")).toUpperCase();
}

/** Calendar days from today to a YYYY-MM-DD deadline (negative when overdue), and a short label. */
export function deadlineInfo(deadline: string | null | undefined): { days: number; label: string } | null {
  if (!deadline) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((new Date(deadline + "T00:00:00").getTime() - today.getTime()) / 86400000);
  const label = new Date(deadline + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return { days, label };
}

export const plural = (n: number, word: string, many = `${word}s`) => `${n.toLocaleString()} ${n === 1 ? word : many}`;
