import { afterEach, describe, expect, it, vi } from "vitest";
import { ago, dayGroup, deadlineInfo, monogram } from "./format";
import { parseHash } from "./stores/router.svelte";

describe("format", () => {
  afterEach(() => vi.useRealTimers());

  it("counts deadline days by calendar date, morning or evening", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 14, 9, 0)); // Oct 14, 09:00
    expect(deadlineInfo("2026-10-13")?.days).toBe(-1);
    expect(deadlineInfo("2026-10-14")?.days).toBe(0);
    vi.setSystemTime(new Date(2026, 9, 14, 23, 0));
    expect(deadlineInfo("2026-10-15")?.days).toBe(1);
    expect(deadlineInfo(null)).toBeNull();
  });

  it("formats ages, date groups and monograms like the old app", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 14, 14, 0));
    const now = Date.now() / 1000;
    expect([ago(now - 30), ago(now - 600), ago(now - 7200), ago(now - 3 * 86400)]).toEqual(["just now", "10m ago", "2h ago", "3d ago"]);
    expect([dayGroup(now - 3600), dayGroup(now - 86400), dayGroup(null)]).toEqual(["Today", "Yesterday", "Date unknown"]);
    expect([monogram("Acme Robotics"), monogram("Stripe"), monogram("")]).toEqual(["AR", "ST", "?"]);
  });

  it("parses hash routes with parameters", () => {
    const { view, params } = parseHash("#people?listing=simplify%3Aacme&kind=team&add=1");
    expect(view).toBe("people");
    expect([params.get("listing"), params.get("kind"), params.get("add")]).toEqual(["simplify:acme", "team", "1"]);
  });
});
