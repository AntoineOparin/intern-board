import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { toastState } from "./stores/toast.svelte";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("request", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends JSON bodies and query strings like the old app", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(json({ total: 0, items: [] })));
    vi.stubGlobal("fetch", fetch);
    await api.listings({ offset: 0, limit: 50, sort: "posted", q: "", hide_tracked: false, region: "CA" });
    expect(fetch.mock.calls[0][0]).toBe("/api/listings?offset=0&limit=50&sort=posted&region=CA");
    await api.track("simplify:a/b", { status: "saved" });
    expect(fetch.mock.calls[1][0]).toBe("/api/tracker/simplify%3Aa%2Fb");
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "PUT", body: '{"status":"saved"}', headers: { "Content-Type": "application/json" } });
  });

  it("shows server errors in a toast unless quiet, and reads FastAPI's validation lists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Unknown listing" }, 404)));
    await expect(api.track("x", {})).rejects.toMatchObject({ message: "Unknown listing", status: 404, shown: true });
    expect(toastState.message).toBe("Request failed: Unknown listing");

    toastState.message = "";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: [{ loc: ["body", "full_name"], msg: "String should have at least 2 characters" }] }, 422)));
    await expect(api.addContact({ listing_id: "x", kind: "team", full_name: "A", title: "", linkedin_url: "", email: "" }, { quiet: true }))
      .rejects.toMatchObject({ message: "Full name: String should have at least 2 characters", shown: false });
    expect(toastState.message).toBe("");
  });

  it("reports an unreachable server", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.meta()).rejects.toThrow("Couldn't reach Intern Board. Is ./run.sh still running?");
  });
});

describe("runJob", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("starts the job, polls every 1.5s with progress, and resolves with the result", async () => {
    const replies = [json({ job_id: "j1" }), json({ status: "running" }), json({ status: "done", result: { ok: 1 } })];
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(replies.shift()));
    vi.stubGlobal("fetch", fetch);
    const progress = vi.fn();
    const done = api.runJob("rank_listings", { limit: 40 }, progress);
    await vi.advanceTimersByTimeAsync(3000);
    await expect(done).resolves.toEqual({ ok: 1 });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ kind: "rank_listings", payload: { limit: 40 } });
    expect(fetch.mock.calls[1][0]).toBe("/api/ai/jobs/j1");
    expect(progress.mock.calls.map(c => c[1])).toEqual(["running", "done"]);
  });

  it("rejects with the job's error, and gives up after 10 minutes", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json({ job_id: "j1" }))
      .mockResolvedValueOnce(json({ status: "error", error: "Claude timed out." })));
    const failed = api.runJob("outreach");
    const check = expect(failed).rejects.toThrow("Claude timed out.");
    await vi.advanceTimersByTimeAsync(1500);
    await check;

    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) =>
      Promise.resolve(url.endsWith("/jobs") ? json({ job_id: "j2" }) : json({ status: "running" }))));
    const slow = api.runJob("outreach");
    const slowCheck = expect(slow).rejects.toThrow("This is taking too long.");
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000 + 3000);
    await slowCheck;
  });
});
