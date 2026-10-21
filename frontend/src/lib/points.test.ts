import { describe, expect, it } from "vitest";
import { entryTitle, indexPoints, newEntry, pointsOf, splitList, swapOptions, withPoints } from "./points";
import type { ProfileData, ResumeEntry } from "./types";
import profileFixture from "../../../e2e/fixtures/profile.json";

const pool = profileFixture.data as unknown as ProfileData;

describe("pointsOf and withPoints", () => {
  it("keeps points and converts legacy bullets", () => {
    expect(pointsOf(pool.experience![0])).toBe(pool.experience![0].points);
    const legacy = pointsOf({ bullets: ["Did a thing.", " ", "Did another."] });
    expect(legacy.map(p => p.phrasings)).toEqual([["Did a thing."], ["Did another."]]);
    expect(new Set(legacy.map(p => p.id)).size).toBe(2);
    expect(legacy[0].id).toMatch(/^p-[0-9a-f]{8}$/);
  });

  it("gives every entry an id and points, dropping legacy bullets", () => {
    const data = {
      experience: [{ organization: "Acme", role: "Dev", location: "", start: "", end: "", bullets: ["Shipped it."] }],
      projects: [{ id: "j-keep", name: "P", tech: [], link: "", date: "", points: [{ id: "p-1", phrasings: ["Built P."] }] }],
    } as unknown as ProfileData;
    const out = withPoints(data);
    expect(out.experience![0].id).toMatch(/^e-/);
    expect(out.experience![0].points[0].phrasings).toEqual(["Shipped it."]);
    expect(out.experience![0]).not.toHaveProperty("bullets");
    expect(out.experience![0].missing_from_resume).toBe(false);
    expect(out.projects![0]).toMatchObject({ id: "j-keep", points: [{ id: "p-1", phrasings: ["Built P."] }] });
    expect(data.experience![0]).toHaveProperty("bullets"); // the input is untouched
  });

  it("makes blank entries with one empty point, and splits tech lists", () => {
    const e = newEntry("experience");
    expect(e.id).toMatch(/^e-/);
    expect(e).toMatchObject({ organization: "", role: "", location: "", start: "", end: "", missing_from_resume: false });
    expect(e.points).toHaveLength(1);
    expect(e.points[0].phrasings).toEqual([""]);
    const p = newEntry("projects");
    expect(p.id).toMatch(/^j-/);
    expect(p).toMatchObject({ name: "", tech: [], link: "", date: "" });
    expect(splitList(" Go, SQLite,, ")).toEqual(["Go", "SQLite"]);
  });

  it("titles entries", () => {
    expect(entryTitle("experience", pool.experience![0])).toBe("Software Developer Intern · Harbourview Labs");
    expect(entryTitle("projects", pool.projects![0])).toBe("Trailmap");
    expect(entryTitle("experience", { id: "e", organization: "", role: "", points: [] } as never)).toBe("Untitled role");
  });
});

describe("swapOptions", () => {
  const entry: ResumeEntry = {
    source_id: "e-harbour",
    bullets: ["Built a Python service that cut report generation from 40 minutes to 6 minutes.", "Wrote integration tests for the service's REST endpoints."],
    refs: [{ point_id: "p-report", phrasing: 0 }, { point_id: "p-tests", phrasing: 0 }],
  };

  it("lists the point's other phrasings and the entry's unused points", () => {
    expect(indexPoints(pool).get("p-report")?.entry.id).toBe("e-harbour");
    const o = swapOptions(entry, 0, pool)!;
    expect(o.phrasings).toEqual([{ text: "Cut report generation from 40 minutes to 6 minutes by building a Python service.", phrasing: 1 }]);
    expect(o.points).toEqual([{ point_id: "p-review", text: "Reviewed pull requests from two other interns." }]);
    // The second bullet's point has one phrasing, so only the unused point is offered.
    expect(swapOptions(entry, 1, pool)).toEqual({ phrasings: [], points: [{ point_id: "p-review", text: "Reviewed pull requests from two other interns." }] });
  });

  it("offers every phrasing of a bullet that was edited by hand", () => {
    const edited = { ...entry, bullets: ["Something I typed.", entry.bullets[1]] };
    expect(swapOptions(edited, 0, pool)!.phrasings.map(p => p.phrasing)).toEqual([0, 1]);
  });

  it("falls back to the point's own entry when the source entry is gone, and returns null when it can't help", () => {
    const moved = { ...entry, source_id: "e-gone" };
    expect(swapOptions(moved, 0, pool)!.points).toHaveLength(1);
    expect(swapOptions({ bullets: ["x"] }, 0, pool)).toBeNull(); // no refs: an older document
    expect(swapOptions({ ...entry, refs: [{ point_id: "p-nope", phrasing: 0 }, null] }, 0, pool)).toBeNull();
    expect(swapOptions(entry, 1, { ...pool, experience: [{ ...pool.experience![0], points: pool.experience![0].points.slice(0, 2) }] })).toBeNull();
    expect(swapOptions(entry, 0, null)).toBeNull();
  });
});
