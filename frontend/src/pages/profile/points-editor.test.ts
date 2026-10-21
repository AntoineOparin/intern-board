// The points editor with the API mocked: edits stay local until Save, and Claude runs only on a click.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import PointsEditor from "./PointsEditor.svelte";
import { profile, editor, suggestions } from "../../lib/stores/profile.svelte";
import type { Profile } from "../../lib/types";
import profileFixture from "../../../../e2e/fixtures/profile.json";

type Call = { method: string; url: string; body: any };
let calls: Call[];
let jobResult: unknown;

function mockApi() {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method || "GET";
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
    calls.push({ method, url, body });
    const reply = (json: unknown) => new Response(JSON.stringify(json), { headers: { "Content-Type": "application/json" } });
    if (url === "/api/ai/jobs") return reply({ job_id: "j1" });
    if (url.startsWith("/api/ai/jobs/")) return reply({ status: "done", result: jobResult });
    if (url === "/api/profile" && method === "PUT") return reply({ ...profileFixture, data: body.data, version: 8, updated_at: 1 });
    return reply({});
  }));
}

const jobCalls = () => calls.filter(c => c.method === "POST" && c.url === "/api/ai/jobs");
const puts = () => calls.filter(c => c.method === "PUT" && c.url === "/api/profile");
const title = "Software Developer Intern · Harbourview Labs";

beforeEach(() => {
  mockApi();
  profile.data = structuredClone(profileFixture) as unknown as Profile;
  editor.draft = null;
  editor.dirty = false;
  suggestions.clear();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("points editor", () => {
  it("lists every point and phrasing, and saves the whole profile once", async () => {
    const user = userEvent.setup();
    render(PointsEditor);
    expect(screen.getAllByRole("article").map(a => a.getAttribute("aria-label"))).toEqual([title, "Trailmap"]);
    expect(screen.getByRole("textbox", { name: `Phrasing 2 of point 1, ${title}` })).toHaveValue("Cut report generation from 40 minutes to 6 minutes by building a Python service.");
    expect(screen.getAllByRole("textbox")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();

    await user.click(screen.getAllByRole("button", { name: "Add phrasing" })[0]);
    const added = screen.getByRole("textbox", { name: `Phrasing 3 of point 1, ${title}` });
    await user.type(added, "Reduced report generation from 40 minutes to 6 minutes.");
    expect(document.getElementById("points-msg")).toHaveTextContent("Unsaved changes");
    expect(puts()).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(document.getElementById("points-msg")).toHaveTextContent("Saved."));
    expect(puts()).toHaveLength(1);
    const sent = puts()[0].body.data;
    expect(sent.name).toBe("Sam Rivera");
    expect(sent.experience[0].points[0].phrasings).toEqual([
      "Built a Python service that cut report generation from 40 minutes to 6 minutes.",
      "Cut report generation from 40 minutes to 6 minutes by building a Python service.",
      "Reduced report generation from 40 minutes to 6 minutes.",
    ]);
    expect(profile.data?.version).toBe(8);
    expect(jobCalls()).toHaveLength(0);
  });

  it("asks Claude only when Suggest variations is clicked, and keeps suggestions locally", async () => {
    const user = userEvent.setup();
    jobResult = { point_id: "p-tests", suggestions: ["Added integration tests for the REST endpoints.", "Covered the REST endpoints with integration tests."], dropped: 1 };
    render(PointsEditor);
    expect(jobCalls()).toHaveLength(0);
    const point = screen.getAllByRole("listitem").find(li => li.classList.contains("pe-point") && within(li).queryByText("Point 2"))!;
    await user.click(within(point).getByRole("button", { name: "Suggest variations" }));
    expect(jobCalls()).toHaveLength(1);
    expect(jobCalls()[0].body).toEqual({ kind: "suggest_phrasings", payload: { point_id: "p-tests" } });
    expect(puts()).toHaveLength(0); // nothing was dirty, so nothing was saved first

    const list = await within(point).findByRole("list", { name: "Suggested phrasings for point 2" }, { timeout: 4000 });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    await user.click(within(list).getAllByRole("button", { name: "Discard" })[1]);
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    await user.click(within(list).getByRole("button", { name: "Keep" }));
    expect(within(point).getByRole("textbox", { name: `Phrasing 2 of point 2, ${title}` })).toHaveValue("Added integration tests for the REST endpoints.");
    expect(within(point).queryByRole("list", { name: /Suggested phrasings/ })).toBeNull();
    expect(puts()).toHaveLength(0); // kept, but not saved yet
    expect(editor.dirty).toBe(true);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("saves unsaved edits before asking Claude, and explains an empty result", async () => {
    const user = userEvent.setup();
    jobResult = { point_id: "p-review", suggestions: [], dropped: 3 };
    render(PointsEditor);
    const box = screen.getByRole("textbox", { name: `Phrasing 1 of point 3, ${title}` });
    await user.clear(box);
    await user.type(box, "Reviewed pull requests from two other interns each week.");
    const point = box.closest(".pe-point") as HTMLElement;
    await user.click(within(point).getByRole("button", { name: "Suggest variations" }));
    await waitFor(() => expect(jobCalls()).toHaveLength(1));
    expect(puts()).toHaveLength(1);
    expect(puts()[0].body.data.experience[0].points[2].phrasings).toEqual(["Reviewed pull requests from two other interns each week."]);
    expect(calls.indexOf(puts()[0])).toBeLessThan(calls.indexOf(jobCalls()[0]));
    await waitFor(() => expect(screen.getByText(/so none were kept/)).toBeInTheDocument(), { timeout: 4000 });
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/so none were kept/)).toBeNull();
  });
});
