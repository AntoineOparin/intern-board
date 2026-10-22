// Points and phrasings (board/profile.py): each experience or project holds points, one fact each,
// said in one or more phrasings. These helpers are pure so they can be tested without a component.
import type { ExperienceEntry, Point, ProfileData, ProjectEntry, ResumeEntry } from "./types";

export type Section = "experience" | "projects";
export type Entry = ExperienceEntry | ProjectEntry;
export const SECTIONS: [Section, string][] = [["experience", "Experience"], ["projects", "Projects"]];
/** Per point, same as profile.MAX_PHRASINGS on the server. */
export const MAX_PHRASINGS = 6;

export function newId(prefix: string): string {
  const hex = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replace(/-/g, "")
    : Math.random().toString(16).slice(2).padEnd(8, "0");
  return `${prefix}-${hex.slice(0, 8)}`;
}

/** The entry's points, built from legacy `bullets` when the entry hasn't been saved in the new shape. */
export function pointsOf(entry: Partial<Entry>): Point[] {
  if (Array.isArray(entry.points)) return entry.points;
  return (entry.bullets ?? []).filter(b => b.trim()).map(b => ({ id: newId("p"), phrasings: [b] }));
}

/** A copy of the profile where every entry has an id and points (and no legacy bullets). */
export function withPoints(data: ProfileData): ProfileData {
  const copy = structuredClone(data);
  for (const [section, , prefix] of [["experience", "", "e"], ["projects", "", "j"]] as [Section, string, string][]) {
    const entries = copy[section];
    if (!Array.isArray(entries)) continue;
    copy[section] = entries.map(e => {
      const { bullets: _legacy, ...rest } = e;
      return { ...rest, id: e.id || newId(prefix), points: pointsOf(e), missing_from_resume: !!e.missing_from_resume };
    }) as never;
  }
  return copy;
}

/** A blank entry with one empty point, for the Add experience / Add project buttons. */
export function newEntry(section: Section): Entry {
  const base = { points: [{ id: newId("p"), phrasings: [""] }], missing_from_resume: false };
  if (section === "experience") return { id: newId("e"), organization: "", role: "", location: "", start: "", end: "", ...base };
  return { id: newId("j"), name: "", tech: [], link: "", date: "", ...base };
}

/** "Go, SQLite" -> ["Go", "SQLite"], for the project tech field. */
export const splitList = (s: string) => s.split(",").map(t => t.trim()).filter(Boolean);

export function entryTitle(section: Section, entry: Entry): string {
  if (section === "experience") {
    const e = entry as ExperienceEntry;
    return [e.role, e.organization].filter(Boolean).join(" · ") || "Untitled role";
  }
  return (entry as ProjectEntry).name || "Untitled project";
}

export type PointHit = { section: Section; entry: Entry; point: Point };

/** Every point in the profile by id. */
export function indexPoints(data: ProfileData | null | undefined): Map<string, PointHit> {
  const index = new Map<string, PointHit>();
  if (!data) return index;
  for (const [section] of SECTIONS) {
    for (const entry of data[section] ?? []) {
      for (const point of pointsOf(entry)) index.set(point.id, { section, entry, point });
    }
  }
  return index;
}

export interface SwapOptions {
  /** Other phrasings of the same point (the fact stays the same). */
  phrasings: { text: string; phrasing: number }[];
  /** Points of the same entry that the resume doesn't use yet. */
  points: { point_id: string; text: string }[];
}

/** What bullet i of a resume entry could be swapped for, or null when the profile can't say. */
export function swapOptions(entry: ResumeEntry, i: number, pool: ProfileData | null | undefined): SwapOptions | null {
  const ref = entry.refs?.[i];
  if (!ref || !pool) return null;
  const hit = indexPoints(pool).get(ref.point_id);
  if (!hit) return null;
  const current = entry.bullets[i];
  const phrasings = hit.point.phrasings.map((text, phrasing) => ({ text, phrasing })).filter(o => o.text !== current);
  const used = new Set((entry.refs ?? []).flatMap(r => (r ? [r.point_id] : [])));
  const owner = [...(pool.experience ?? []), ...(pool.projects ?? [])].find(e => e.id === entry.source_id) ?? hit.entry;
  const points = pointsOf(owner).filter(p => !used.has(p.id)).map(p => ({ point_id: p.id, text: p.phrasings[0] }));
  return phrasings.length || points.length ? { phrasings, points } : null;
}
