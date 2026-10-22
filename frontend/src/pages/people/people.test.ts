// Find People components with the API mocked: credit states, and no Claude request without a click.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import Results from "./Results.svelte";
import Choose from "./Choose.svelte";
import { people, drafts, writing, draftErrors } from "../../lib/stores/people.svelte";
import { credits } from "../../lib/stores/credits.svelte";
import type { PeopleSession, ProspeoAccount } from "../../lib/types";
import sessionFixture from "../../../../e2e/fixtures/people-session-acme.json";
import accounts from "../../../../e2e/fixtures/prospeo-accounts.json";
import draftsFixture from "../../../../e2e/fixtures/people-drafts.json";

type Call = { method: string; url: string; body: any };
let calls: Call[];

function mockApi() {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method || "GET";
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
    calls.push({ method, url, body });
    const reply = (json: unknown) => new Response(JSON.stringify(json), { headers: { "Content-Type": "application/json" } });
    if (url === "/api/ai/jobs") return reply({ job_id: "j1" });
    if (url.startsWith("/api/ai/jobs/")) return reply({ status: "running" });
    if (url.startsWith("/api/integrations/prospeo")) return reply(credits.account);
    return reply({});
  }));
}

// The page shares one session through the store; the components get it as a prop too.
const session = (): PeopleSession => (people.session = structuredClone(sessionFixture) as PeopleSession);
const jobCalls = () => calls.filter(c => c.method === "POST" && c.url === "/api/ai/jobs");

beforeEach(() => {
  mockApi();
  drafts.clear(); writing.clear(); draftErrors.clear();
  people.open = "pr-jordan";
  people.channel = {};
  people.add = false;
  for (const d of draftsFixture.items) drafts.set(`${d.person_id}|${d.channel}`, d as any);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("credits", () => {
  it("shows the remaining credits, a low warning, and the empty state", async () => {
    credits.account = accounts.ok as ProspeoAccount;
    const view = render(Results, { session: session(), kind: "recruiters" });
    expect(view.container.querySelector(".fp-credits")).toHaveTextContent("57 credits left");
    expect(screen.getByRole("button", { name: "Search again · 1 credit" })).toBeEnabled();
    cleanup();

    credits.account = accounts.low as ProspeoAccount;
    const low = render(Results, { session: session(), kind: "recruiters" });
    expect(low.container.querySelector(".fp-credits")).toHaveTextContent("4 credits left · running low");
    expect(low.container.querySelector(".fp-credits")).toHaveClass("low");
    cleanup();

    credits.account = accounts.empty as ProspeoAccount;
    const empty = render(Results, { session: session(), kind: "recruiters" });
    expect(empty.container.querySelector(".fp-credits")).toHaveTextContent("No credits left · renews Nov 1");
    expect(screen.getByRole("button", { name: "No credits left" })).toBeDisabled();
  });

  it("out of credits: paid actions are replaced, free ones stay", async () => {
    credits.account = accounts.empty as ProspeoAccount;
    people.open = "pr-priya";
    const view = render(Results, { session: session(), kind: "recruiters" });
    const priya = view.container.querySelector('.fp-person[data-person="pr-priya"]') as HTMLElement;
    expect(within(priya).getByText("Email available · no credits left")).toBeInTheDocument();
    expect(within(priya).queryByRole("button", { name: /Find email/ })).toBeNull();
  });

  it("the choice cards turn off new searches at 0 credits but keep saved results", () => {
    credits.account = accounts.empty as ProspeoAccount;
    const view = render(Choose, { session: session() });
    expect(view.container.querySelector('.fp-choice[data-kind="recruiters"]')).toBeEnabled();
    expect(view.container.querySelector('.fp-choice[data-kind="team"]')).toBeDisabled();
    expect(screen.getByText(/You're out of Prospeo credits until Nov 1\./)).toBeInTheDocument();
  });
});

describe("intro drafts", () => {
  it("opening cards and switching message type never asks Claude", async () => {
    credits.account = accounts.ok as ProspeoAccount;
    const user = userEvent.setup();
    render(Results, { session: session(), kind: "recruiters" });
    await user.click(screen.getByRole("radio", { name: "LinkedIn note" }));
    for (const name of [/Priya Nair/, /Alex Moreau/, /Jordan Okafor/]) await user.click(screen.getByRole("button", { name }));
    expect(jobCalls()).toHaveLength(0);
  });

  it("Write starts exactly one outreach job, and only on click", async () => {
    credits.account = accounts.ok as ProspeoAccount;
    people.open = "pr-priya";
    const user = userEvent.setup();
    render(Results, { session: session(), kind: "recruiters" });
    expect(jobCalls()).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Write LinkedIn note" }));
    expect(jobCalls()).toHaveLength(1);
    expect(jobCalls()[0].body).toEqual({ kind: "outreach", payload: {
      listing_id: "simplify:acme-swe-27", person_id: "pr-priya", channel: "linkedin_note", recipient_type: "recruiter" } });
  });
});
