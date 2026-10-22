import * as api from "../api";
import { deadlineInfo } from "../format";
import type { Status, TrackerItem, TrackerUpdate } from "../types";

export const tracker = $state({
  statuses: ["saved", "applied", "interviewing", "offer", "rejected"] as Status[],
  items: [] as TrackerItem[],
  loaded: false,
});

export const trackedById = () => new Map(tracker.items.map(i => [i.id, i]));

/** Open items due in the next 7 days ("Deadlines this week"). */
export function dueThisWeek(items: TrackerItem[]): number {
  return items.filter(i => {
    const d = deadlineInfo(i.deadline);
    return d && d.days >= 0 && d.days <= 7 && !["offer", "rejected"].includes(i.status);
  }).length;
}

export async function loadTracker() {
  const data = await api.tracker();
  tracker.statuses = data.statuses;
  tracker.items = data.items;
  tracker.loaded = true;
}

export async function updateTracked(id: string, update: TrackerUpdate) {
  await api.track(id, update);
  await loadTracker();
}

export async function removeTracked(id: string) {
  await api.untrack(id);
  await loadTracker();
}
