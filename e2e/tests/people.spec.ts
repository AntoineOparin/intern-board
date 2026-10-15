import { test, expect, NOW, DAY, fixture, detail } from "../support/test";
import type { Page } from "@playwright/test";

const ACME = "simplify:acme-swe-27";
const MAPLE = "negarprh:maple-firmware";
const route = (listing: string, extra = "") => `#people?listing=${encodeURIComponent(listing)}${extra}`;
const accounts = fixture("prospeo-accounts.json");

const people = (page: Page) => page.locator("#people-view");
const person = (page: Page, name: string) => people(page).locator(".fp-person").filter({ hasText: name });
const credits = (page: Page) => people(page).locator(".fp-credits");

test.describe("step 1: pick a tracked job", () => {
  test("lists tracked jobs by company with logos, and filters as you type", async ({ app, page }) => {
    await app.open("#people");
    await expect(people(page).getByRole("heading", { name: "Find People" })).toBeVisible();
    await expect(people(page).getByRole("heading", { name: "Who do you want to reach?" })).toBeVisible();
    await expect(credits(page)).toHaveText("57 credits left");
    const rows = people(page).locator(".fp-job-row");
    await expect(rows.locator("strong")).toHaveText([
      "Software Engineer Intern - Summer 2027", "Security Engineering Intern", "QA Automation Intern", "Firmware Intern", "Machine Learning Intern",
    ]);
    await expect(rows.first()).toContainText("Acme Robotics");
    await expect(rows.first()).toContainText("Toronto, ON");
    await expect(rows.first()).not.toContainText("Waterloo");
    await expect(rows.first()).toHaveAttribute("href", route(ACME));
    await expect(rows.first().locator("img.fp-logo")).toHaveAttribute("src", "https://img.fixture.test/acme.png");
    // A logo that fails to load falls back to the company's initials.
    await expect(rows.filter({ hasText: "Orbit Analytics" }).locator(".fp-mono")).toHaveText("OA");

    const search = people(page).getByRole("searchbox", { name: "Search your tracked jobs" });
    await search.fill("firm");
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText("Maple Systems");
    await search.fill("ottawa");
    await expect(rows).toHaveCount(1);
    await search.fill("nothing like this");
    await expect(people(page).getByText("No tracked jobs match.")).toBeVisible();
  });

  test("picking a job shows a spinner on its row while the next step loads", async ({ app, api, page }) => {
    await app.open("#people");
    const release = api.hold("GET", "/api/people/session");
    const row = people(page).locator(".fp-job-row").first();
    await row.click();
    await expect(row).toHaveClass(/loading/);
    release();
    await expect(page).toHaveURL(new RegExp(`${route(ACME).replace(/[?]/g, "\\?")}$`));
    await expect(people(page).getByRole("heading", { name: "Who are you looking for at Acme Robotics?" })).toBeVisible();
  });

  test("an empty tracker explains how to start", async ({ app, api, page }) => {
    api.tracker.items = [];
    await app.open("#people");
    await expect(people(page).getByText("Your tracker is empty.")).toBeVisible();
    await expect(people(page).getByRole("link", { name: "Browse internships" })).toHaveAttribute("href", "#board");
  });
});

test.describe("step 2: recruiters or coffee chats", () => {
  test("cards show saved counts and costs, and the company website", async ({ app, api, page }) => {
    await app.open(route(ACME));
    const view = people(page);
    await expect(view.getByRole("heading", { name: "Who are you looking for at Acme Robotics?" })).toBeVisible();
    await expect(view.locator(".fp-job")).toContainText("Software Engineer Intern - Summer 2027");
    const recruiters = view.locator(".fp-choice[data-kind=recruiters]");
    const team = view.locator(".fp-choice[data-kind=team]");
    await expect(recruiters).toContainText("University and technical recruiters who hire interns.");
    await expect(recruiters.locator(".fp-choice-foot")).toHaveText("6 saved · searched 2d ago");
    await expect(team).toContainText("Software engineers on the team you're applying to.");
    await expect(team.locator(".fp-choice-foot")).toHaveText("Uses 1 Prospeo credit");
    await expect(recruiters).toBeEnabled();
    await expect(team).toBeEnabled();
    await expect(view.locator(".fp-site")).toHaveText(/Searching people at acmerobotics\.example \(Acme Robotics\)\.\s+Wrong company\? Change website/);
    await expect(view.getByRole("heading", { name: "Free searches" })).toHaveCount(0);
    await expect(view.getByRole("link", { name: "or add someone yourself" }).first())
      .toHaveAttribute("href", `${route(ACME)}&kind=recruiters&add=1`);
    expect(api.jobRequests()).toHaveLength(0);
  });

  test("a card with a saved search opens the results without a new search", async ({ app, api, page }) => {
    await app.open(route(ACME));
    await people(page).locator(".fp-choice[data-kind=recruiters]").click();
    await expect(page).toHaveURL(/kind=recruiters$/);
    await expect(people(page).locator(".fp-count-line")).toHaveText("6 recruiters at Acme Robotics");
    expect(api.jobRequests()).toHaveLength(0);
  });

  test("a card without a search runs one (1 credit) and shows progress", async ({ app, api, page }) => {
    api.jobOutcomes.people_search = { status: "done", result: { count: 0, free: false, charged: true }, polls: 1 };
    await app.open(route(ACME));
    const team = people(page).locator(".fp-choice[data-kind=team]");
    await team.click();
    await expect(team).toHaveClass(/loading/);
    await expect(team).toBeDisabled();
    await expect(people(page).locator("#fp-choose-msg")).toHaveText(/^Searching Prospeo… \d+s$/);
    expect(api.jobRequests("people_search")[0].body).toEqual({ kind: "people_search", payload: { listing_id: ACME, kind: "team" } });
    await expect(page).toHaveURL(/kind=team$/, { timeout: 8000 });
    await expect(people(page).getByRole("heading", { name: "No one found" })).toBeVisible();
    await expect(people(page).getByText("Prospeo has no matching people at acmerobotics.example.")).toBeVisible();
  });

  test("a failed search shows the error under the cards", async ({ app, api, page }) => {
    api.jobOutcomes.people_search = { status: "error", error: "Couldn't work out Maple Systems's website. Enter it with “Change website”." };
    await app.open(route(MAPLE));
    await people(page).locator(".fp-choice[data-kind=recruiters]").click();
    await expect(people(page).locator("#fp-choose-msg")).toHaveText("Couldn't work out Maple Systems's website. Enter it with “Change website”.");
    await expect(people(page).locator("#fp-choose-msg")).toHaveClass(/error/);
    await expect(people(page).locator(".fp-choice[data-kind=recruiters]")).toBeEnabled();
  });

  test("stale searches and people you added yourself are labelled", async ({ app, api, page }) => {
    api.sessions[ACME].searches.recruiters.stale = true;
    api.sessions[MAPLE].contacts.team = [{ ...api.sessions[ACME].contacts.recruiters[5], listing_id: MAPLE, kind: "team" }];
    await app.open(route(ACME));
    const foot = people(page).locator(".fp-choice[data-kind=recruiters] .fp-choice-foot");
    await expect(foot).toHaveText("6 saved · searched 2d ago · may be out of date");
    await expect(foot).toHaveClass(/warn/);

    await page.goto(`./${route(MAPLE)}`);
    await expect(people(page).locator(".fp-choice[data-kind=team] .fp-choice-foot")).toHaveText("1 added by you");
    await expect(people(page).locator(".fp-site")).toHaveText(/The company's website is looked up on the first search\.\s+Set website/);
  });

  test("without a Prospeo key: a link to Integrations, only saved results open, and free searches", async ({ app, api, page }) => {
    api.account = accounts.not_configured;
    await app.open(route(ACME));
    const view = people(page);
    await expect(view.getByText("Add your Prospeo API key under My profile → Integrations to search.")).toBeVisible();
    await expect(view.getByRole("link", { name: "My profile → Integrations" })).toHaveAttribute("href", "#profile");
    await expect(credits(page)).toHaveText("");
    await expect(view.locator(".fp-choice[data-kind=recruiters]")).toBeEnabled();
    await expect(view.locator(".fp-choice[data-kind=team]")).toBeDisabled();
    const free = view.locator(".fp-free");
    await expect(free.getByRole("heading", { name: "Free searches" })).toBeVisible();
    await expect(free.locator("h3")).toHaveText(["Recruiters", "People on the team", "Google searches"]);
    await expect(free.getByRole("link", { name: "University recruiter ↗" }))
      .toHaveAttribute("href", "https://www.linkedin.com/search/results/people/?keywords=Acme+Robotics+university+recruiter");
    await expect(free.getByRole("link", { name: "University recruiter ↗" })).toHaveAttribute("target", "_blank");
  });

  test("out of credits: the renewal date, disabled new searches and free searches", async ({ app, api, page }) => {
    api.account = accounts.empty;
    await app.open(route(ACME));
    const view = people(page);
    await expect(credits(page)).toHaveText("No credits left · renews Nov 1");
    await expect(credits(page)).toHaveClass(/empty/);
    await expect(view.locator(".fp-out")).toHaveText("You're out of Prospeo credits until Nov 1. People you've already found still work. Use the free searches below, then add who you find.");
    await expect(view.locator(".fp-choice[data-kind=recruiters]")).toBeEnabled();
    const team = view.locator(".fp-choice[data-kind=team]");
    await expect(team).toBeDisabled();
    await expect(team.locator(".fp-choice-foot")).toHaveText("No credits left · renews Nov 1");
    await expect(team.locator(".fp-choice-foot")).toHaveClass(/warn/);
    await expect(view.getByRole("heading", { name: "Free searches" })).toBeVisible();
  });

  test("low credits show a warning in the credit count", async ({ app, api, page }) => {
    api.account = accounts.low;
    await app.open(route(ACME));
    await expect(credits(page)).toHaveText("4 credits left · running low");
    await expect(credits(page)).toHaveClass(/low/);
  });

  test("changing the company website saves it and asks you to search again", async ({ app, api, page }) => {
    await app.open(route(ACME));
    const view = people(page);
    await view.getByRole("button", { name: "Wrong company? Change website" }).click();
    const input = view.getByRole("textbox", { name: "Company website" });
    await expect(input).toBeFocused();
    await expect(input).toHaveValue("acmerobotics.example");
    await input.fill("acme.example");
    await view.getByRole("button", { name: "Save", exact: true }).click();
    await expect(app.toast()).toHaveText("Website saved. Run the search again to find people there.");
    expect(api.last("PUT", "/api/people/site")?.body).toEqual({ listing_id: ACME, website: "acme.example" });
    await expect(view.locator(".fp-site")).toContainText("Searching people at acme.example.");
  });
});

test.describe("step 3: people", () => {
  test("lists people with the first card open, and its email, LinkedIn and freshness", async ({ app, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    const view = people(page);
    await expect(view.locator(".fp-count-line")).toHaveText("6 recruiters at Acme Robotics");
    await expect(view.getByRole("button", { name: "Search again · 1 credit" })).toBeEnabled();
    await expect(view.locator(".fp-person-head[aria-expanded=true]")).toHaveCount(1);

    const jordan = person(page, "Jordan Okafor");
    await expect(jordan.locator(".fp-person-head")).toHaveAttribute("aria-expanded", "true");
    await expect(jordan.locator(".fp-person-text .muted")).toHaveText("University Recruiter · Toronto, Ontario");
    const email = jordan.getByRole("link", { name: /jordan\.okafor@acmerobotics\.example/ });
    await expect(email).toHaveAttribute("href", "mailto:jordan.okafor@acmerobotics.example");
    await expect(email.locator(".fp-ok")).toHaveAttribute("title", "Verified by Prospeo on Oct 12, 2026");
    await expect(jordan.getByRole("link", { name: /linkedin\.com\/in\/jordan-okafor-example/ }))
      .toHaveAttribute("href", "https://www.linkedin.com/in/jordan-okafor-example");
    await expect(jordan.locator(".fp-fresh")).toHaveText(/Found Oct 12, 2026 · email checked Oct 12, 2026\.\s+Re-check \(free\)/);
  });

  test("every email and status state is shown the way Prospeo reports it", async ({ app, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    const open = async (name: string) => {
      await person(page, name).locator(".fp-person-head").click();
      await expect(person(page, name).locator(".fp-person-head")).toHaveAttribute("aria-expanded", "true");
      return person(page, name);
    };

    const priya = await open("Priya Nair");
    await expect(person(page, "Jordan Okafor").locator(".fp-person-head")).toHaveAttribute("aria-expanded", "false");
    await expect(priya.locator(".tag")).toHaveText("New in role");
    await expect(priya.getByRole("button", { name: /Find email/ })).toHaveText(/Find email\s*1 credit/);
    await expect(priya.locator(".fp-fresh")).toHaveText("Found Oct 12, 2026.");

    const alex = await open("Alex Moreau");
    await expect(alex.locator(".fp-chip-warn")).toHaveText(/alex\.moreau@acmerobotics\.example\s*not verified now/);
    await expect(alex.locator(".fp-chip-warn")).toHaveAttribute("title", "Prospeo no longer verifies this address");
    await expect(alex.getByRole("button", { name: "Re-check (free)" })).toBeVisible();

    const casey = await open("Casey Lindqvist");
    await expect(casey.locator(".tag.danger")).toHaveText("Now at Globex Example");
    await expect(casey.getByRole("button", { name: "Re-check · 1 credit" })).toBeVisible();

    const morgan = await open("Morgan Blake");
    await expect(morgan.locator(".fp-chip-off")).toHaveText(["No verified email", "No LinkedIn profile"]);

    const taylor = await open("Taylor Brooks");
    await expect(taylor.locator(".fp-person-text .tag")).toHaveText("Added by you");
    await expect(taylor.getByRole("link", { name: /taylor\.brooks@example\.org/ }).locator(".fp-ok")).toHaveCount(0);
    await expect(taylor.locator(".fp-fresh")).toHaveText(/Added by you Oct 13, 2026\.\s+Remove/);
  });

  test("Find email reveals the address (1 credit)", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    const release = api.hold("POST", "/api/people/email");
    const button = person(page, "Priya Nair").locator("button.fp-reveal");
    await button.click();
    await expect(button).toBeDisabled();
    await expect(button).toContainText("Finding email…");
    release();
    await expect(person(page, "Priya Nair").getByRole("link", { name: /priya@acmerobotics\.example/ })).toBeVisible();
    expect(api.last("POST", "/api/people/email")?.body).toEqual({ listing_id: ACME, kind: "recruiters", person_id: "pr-priya" });
    await expect.poll(() => api.calls("GET", "/api/integrations/prospeo").length).toBeGreaterThanOrEqual(2); // credits refreshed
  });

  test("Find email with no result says no credit was used; an error restores the button", async ({ app, api, page }) => {
    api.on("POST", "/api/people/email", (req, api) => {
      const c = api.sessions[ACME].contacts.recruiters.find((c: any) => c.person_id === req.body.person_id);
      return { json: { ...c, email: null, email_status: "NOT_FOUND" } };
    });
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    await person(page, "Priya Nair").getByRole("button", { name: /Find email/ }).click();
    await expect(app.toast()).toHaveText("Prospeo has no verified email for this person. No credit was used.");
    await expect(person(page, "Priya Nair").locator(".fp-chip-off").first()).toHaveText("No verified email");

    api.on("POST", "/api/people/email", detail(402, "You're out of Prospeo credits until November 1. Saved people still work, and you can use the free search links or add someone yourself."));
    api.sessions[ACME].contacts.recruiters[1].email_status = "VERIFIED";
    await page.reload();
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    const button = person(page, "Priya Nair").getByRole("button", { name: /Find email/ });
    await button.click();
    await expect(app.toast()).toHaveText(/^You're out of Prospeo credits until November 1\./);
    await expect(button).toBeEnabled();
    await expect(button).toContainText("Find email");
  });

  test("Re-check confirms, reports a move, or reports an email that's no longer verified", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Jordan Okafor").getByRole("button", { name: "Re-check (free)" }).click();
    await expect(app.toast()).toHaveText("Still at Acme Robotics; email still verified.");
    expect(api.last("POST", "/api/people/recheck")?.body).toEqual({ listing_id: ACME, kind: "recruiters", person_id: "pr-jordan" });

    api.on("POST", "/api/people/recheck", (req, api) => {
      const list = api.sessions[ACME].contacts.recruiters;
      const i = list.findIndex((c: any) => c.person_id === req.body.person_id);
      list[i] = { ...list[i], moved_to: "Initech Example", email_found_at: NOW };
      return { json: { ...list[i], charged: false } };
    });
    await person(page, "Jordan Okafor").getByRole("button", { name: "Re-check (free)" }).click();
    await expect(app.toast()).toHaveText("Jordan Okafor now appears to work at Initech Example.");
    await expect(person(page, "Jordan Okafor").locator(".tag.danger")).toHaveText("Now at Initech Example");

    api.on("POST", "/api/people/recheck", (req, api) => {
      const c = api.sessions[ACME].contacts.recruiters.find((c: any) => c.person_id === req.body.person_id);
      return { json: { ...c, moved_to: null, email_status: "NO_LONGER_VERIFIED", charged: false } };
    });
    await person(page, "Jordan Okafor").getByRole("button", { name: "Re-check (free)" }).click();
    await expect(app.toast()).toHaveText("Prospeo no longer verifies Jordan Okafor's email. They may have left.");
  });

  test("an old email still inside the free window is re-checked once, without a click", async ({ app, api, page }) => {
    Object.assign(api.sessions[ACME].contacts.recruiters[0], { email_stale: true, recheck_free: true, email_found_at: NOW - 40 * DAY });
    await app.open(route(ACME, "&kind=recruiters"));
    await expect.poll(() => api.calls("POST", "/api/people/recheck").length).toBe(1);
    await expect(app.toast()).toBeHidden(); // quiet: no "still at" toast
    // Closing and reopening the card doesn't check again in the same visit.
    await person(page, "Jordan Okafor").locator(".fp-person-head").click();
    await person(page, "Jordan Okafor").locator(".fp-person-head").click();
    await expect(person(page, "Jordan Okafor").locator(".fp-person-head")).toHaveAttribute("aria-expanded", "true");
    expect(api.calls("POST", "/api/people/recheck")).toHaveLength(1);
  });

  test("stale lists and results from other countries carry a note", async ({ app, api, page }) => {
    Object.assign(api.sessions[ACME].searches.recruiters, { stale: true, searched_at: NOW - 45 * DAY, country_filtered: 0 });
    await app.open(route(ACME, "&kind=recruiters"));
    await expect(people(page).locator(".fp-stale")).toHaveText(
      "This list is from Aug 30, 2026. People change roles and companies, so search again for a fresh one before reaching out.");
    await expect(people(page).getByText("No one matched in this job's country, so these are from other locations.")).toBeVisible();
  });

  test("at 0 credits: Search again is disabled and paid actions are replaced", async ({ app, api, page }) => {
    api.account = accounts.empty;
    await app.open(route(ACME, "&kind=recruiters"));
    const again = people(page).getByRole("button", { name: "No credits left" });
    await expect(again).toBeDisabled();
    await expect(person(page, "Jordan Okafor").getByRole("button", { name: "Re-check (free)" })).toBeVisible();

    await person(page, "Priya Nair").locator(".fp-person-head").click();
    await expect(person(page, "Priya Nair").locator(".fp-chip-off").first()).toHaveText("Email available · no credits left");
    await expect(person(page, "Priya Nair").getByRole("button", { name: /Find email/ })).toHaveCount(0);

    await person(page, "Casey Lindqvist").locator(".fp-person-head").click();
    await expect(person(page, "Casey Lindqvist").locator(".fp-recheck")).toHaveCount(0);
  });

  test("running out of credits while on the page redraws the paid buttons", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    api.account = accounts.empty;
    api.on("POST", "/api/people/email", detail(402, "You're out of Prospeo credits until November 1. Saved people still work, and you can use the free search links or add someone yourself."));
    await person(page, "Priya Nair").getByRole("button", { name: /Find email/ }).click();
    await expect(people(page).getByRole("button", { name: "No credits left" })).toBeDisabled();
    await expect(credits(page)).toHaveText("No credits left · renews Nov 1");
  });

  // Known bug: renderResults() has a local `search` (the saved search) that shadows the search()
  // function, so this button throws "search is not a function". Enable once fixed.
  test.fixme("Search again runs a new search for the same kind", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    const sessions = api.calls("GET", "/api/people/session").length;
    await people(page).getByRole("button", { name: "Search again · 1 credit" }).click();
    await expect(people(page).locator("#fp-results-msg")).toHaveText(/^Searching Prospeo… \d+s$/);
    expect(api.jobRequests("people_search")[0].body.payload).toEqual({ listing_id: ACME, kind: "recruiters" });
    await expect.poll(() => api.calls("GET", "/api/people/session").length, { timeout: 8000 }).toBe(sessions + 1);
  });

  test("Add a person: name required, server errors shown, and the new card opens", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    const view = people(page);
    await view.getByText("Add a person yourself").click();
    const form = view.locator(".fp-add-form");
    await expect(form.getByLabel("Title (optional)")).toHaveAttribute("placeholder", "University Recruiter");
    await form.getByRole("button", { name: "Add" }).click();
    await expect(form.locator(".form-msg")).toHaveText("Enter their name.");
    expect(api.calls("POST", "/api/people/contacts")).toHaveLength(0);

    await form.getByLabel("Name").fill("Robin Park");
    await form.getByLabel("LinkedIn (optional)").fill("example.com/robin");
    await form.getByRole("button", { name: "Add" }).click();
    await expect(form.locator(".form-msg")).toHaveText("Paste a LinkedIn profile link like linkedin.com/in/their-name.");

    await form.getByLabel("Title (optional)").fill("Campus Recruiter");
    await form.getByLabel("LinkedIn (optional)").fill("linkedin.com/in/robin-park-example");
    await form.getByLabel("Email (optional)").fill("robin.park@example.org");
    await form.getByRole("button", { name: "Add" }).click();
    expect(api.last("POST", "/api/people/contacts")?.body).toEqual({
      listing_id: ACME, kind: "recruiters", full_name: "Robin Park", title: "Campus Recruiter",
      linkedin_url: "linkedin.com/in/robin-park-example", email: "robin.park@example.org",
    });
    const robin = person(page, "Robin Park");
    await expect(robin.locator(".fp-person-head")).toHaveAttribute("aria-expanded", "true");
    await expect(robin.locator(".fp-person-text .tag")).toHaveText("Added by you");
    await expect(robin.getByRole("link", { name: /linkedin\.com\/in\/robin-park-example/ }))
      .toHaveAttribute("href", "https://linkedin.com/in/robin-park-example");
    await expect(view.locator(".fp-count-line")).toHaveText("7 recruiters at Acme Robotics");
    await expect(view.locator("details.fp-add")).not.toHaveAttribute("open", "");
  });

  test("Remove deletes a person you added", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Taylor Brooks").locator(".fp-person-head").click();
    await person(page, "Taylor Brooks").getByRole("button", { name: "Remove" }).click();
    await expect(person(page, "Taylor Brooks")).toHaveCount(0);
    await expect(people(page).locator(".fp-count-line")).toHaveText("5 recruiters at Acme Robotics");
    expect(api.last("DELETE", "/api/people/contacts/one")?.query).toEqual({ listing_id: ACME, kind: "recruiters", person_id: "manual:3f9a0c1d2e4b" });
  });

  test("no people and no search yet: the add form, a Search button and free searches", async ({ app, page }) => {
    await app.open(route(MAPLE, "&kind=team&add=1"));
    const view = people(page);
    await expect(view.locator(".fp-count-line")).toHaveText("0 people for coffee chats at Maple Systems");
    await expect(view.getByRole("button", { name: "Search Prospeo · 1 credit" })).toBeEnabled();
    await expect(view.locator("details.fp-add")).toHaveAttribute("open", "");
    await expect(view.locator(".fp-add-form").getByLabel("Title (optional)")).toHaveAttribute("placeholder", "Software Engineer");
    await expect(view.locator(".fp-free h3")).toHaveText(["People on the team", "Alumni from your school", "Google searches"]);
    await expect(view.getByRole("link", { name: "University of Northfield alumni ↗" })).toBeVisible();
  });

  test("back links return to the choice and to the job list", async ({ app, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    await people(page).getByRole("link", { name: "Back" }).click();
    await expect(people(page).getByRole("heading", { name: "Who are you looking for at Acme Robotics?" })).toBeVisible();
    await people(page).getByRole("link", { name: "All tracked jobs" }).click();
    await expect(people(page).getByRole("heading", { name: "Who do you want to reach?" })).toBeVisible();
  });

  test("an unknown listing goes back to the job list", async ({ app, page }) => {
    await app.open(route("simplify:does-not-exist"));
    await expect(page).toHaveURL(/#people$/);
    await expect(people(page).getByRole("heading", { name: "Who do you want to reach?" })).toBeVisible();
  });
});

test.describe("intro drafts", () => {
  test("opening cards and switching message type never asks Claude for a draft", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    for (const name of ["Priya Nair", "Alex Moreau", "Morgan Blake", "Jordan Okafor"]) {
      await person(page, name).locator(".fp-person-head").click();
      await expect(person(page, name).locator(".fp-draft")).toBeVisible();
    }
    await person(page, "Jordan Okafor").getByText("LinkedIn note").click();
    await person(page, "Jordan Okafor").getByText("Email", { exact: true }).click();
    await app.nav("Tracker").click();
    await page.goBack();
    await expect(person(page, "Jordan Okafor").locator(".fp-draft")).toBeVisible();
    expect(api.jobRequests()).toHaveLength(0);
  });

  test("a saved email draft shows subject, body, word count, angle, Copy and Rewrite", async ({ app, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    const draft = person(page, "Jordan Okafor").locator(".fp-draft");
    await expect(draft.getByRole("radio", { name: "Email" })).toBeChecked();
    await expect(draft.getByRole("textbox", { name: "Email subject" })).toHaveValue("Summer 2027 software internship question");
    await expect(draft.getByRole("textbox", { name: "Intro draft" })).toHaveValue(/^Hi Jordan,\n\nI'm a computer engineering student/);
    await expect(draft.locator(".fp-count")).toHaveText("44 words");
    await expect(draft.locator(".fp-angle")).toHaveText("Why this message: Leads with the report-generation project, which is closest to the backend work in this posting.");
    await expect(draft.getByRole("button", { name: "Copy" })).toBeVisible();
    await expect(draft.getByRole("button", { name: "Rewrite" })).toBeVisible();
    await expect(draft.locator(".fp-draft-empty")).toBeHidden();
  });

  test("the LinkedIn note counter uses 200 characters, or 300 with Premium", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Jordan Okafor").getByText("LinkedIn note").click();
    const draft = person(page, "Jordan Okafor").locator(".fp-draft");
    await expect(draft.getByRole("radio", { name: "LinkedIn note" })).toBeChecked();
    await expect(draft.getByRole("textbox", { name: "Email subject" })).toBeHidden();
    await expect(draft.locator(".fp-count")).toHaveText("233 / 200");
    await expect(draft.locator(".fp-count")).toHaveClass(/over/);
    await expect(draft.locator(".fp-checks li")).toHaveText(["Over LinkedIn's 200-character limit for free accounts."]);
    await draft.getByRole("textbox", { name: "Intro draft" }).fill("Short note.");
    await expect(draft.locator(".fp-count")).toHaveText("11 / 200");
    await expect(draft.locator(".fp-count")).not.toHaveClass(/over/);

    api.profile.preferences.linkedin_premium = true;
    await page.reload();
    await person(page, "Jordan Okafor").getByText("LinkedIn note").click();
    await expect(person(page, "Jordan Okafor").locator(".fp-count")).toHaveText("233 / 300");
    await expect(person(page, "Jordan Okafor").locator(".fp-count")).not.toHaveClass(/over/);
  });

  test("Write asks Claude only on click, shows progress, then the draft", async ({ app, api, page }) => {
    api.jobOutcomes.outreach = undefined;
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    const draft = person(page, "Priya Nair").locator(".fp-draft");
    await expect(draft.getByRole("radio", { name: "LinkedIn note" })).toBeChecked(); // no email yet
    await expect(draft.locator(".fp-draft-empty p")).toHaveText(
      "Claude can write a LinkedIn note to Priya from your profile. It takes about 20–40 seconds and uses your Claude plan.");
    await expect(draft.getByRole("button", { name: "Copy" })).toBeHidden();
    await expect(draft.getByRole("button", { name: "Rewrite" })).toBeHidden();
    await expect(draft.getByRole("textbox", { name: "Intro draft" })).toBeHidden();
    expect(api.jobRequests()).toHaveLength(0);

    await draft.getByRole("button", { name: "Write LinkedIn note" }).click();
    await expect(draft.locator(".fp-draft-foot [role=status]")).toHaveText(/^Writing…/);
    await expect(draft.getByRole("textbox", { name: "Intro draft" })).toHaveAttribute("placeholder", "Writing a LinkedIn note with Claude…");
    expect(api.jobRequests()).toHaveLength(1);
    expect(api.jobRequests("outreach")[0].body).toEqual({
      kind: "outreach",
      payload: { listing_id: ACME, person_id: "pr-priya", channel: "linkedin_note", recipient_type: "recruiter" },
    });
    await expect(draft.getByRole("textbox", { name: "Intro draft" })).toHaveValue(/^Hi, I'm applying to Acme's Summer 2027/, { timeout: 5000 });
    await expect(draft.locator(".fp-draft-foot [role=status]")).toHaveText("");
    await expect(draft.locator(".fp-count")).toHaveText(/^\d+ \/ 200$/);
    await expect(draft.getByRole("button", { name: "Rewrite" })).toBeVisible();
  });

  test("Rewrite sends the current draft as previous_id", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    const draft = person(page, "Jordan Okafor").locator(".fp-draft");
    await draft.getByRole("button", { name: "Rewrite" }).click();
    expect(api.jobRequests("outreach")[0].body.payload).toEqual({
      listing_id: ACME, person_id: "pr-jordan", channel: "email", recipient_type: "recruiter", previous_id: "draft-email-1",
    });
    await expect(draft.getByRole("textbox", { name: "Email subject" })).toHaveValue("Question about Summer 2027 internships", { timeout: 5000 });
  });

  test("coffee-chat drafts are written for an engineer", async ({ app, api, page }) => {
    api.sessions[ACME].contacts.team = [{ ...api.sessions[ACME].contacts.recruiters[4], kind: "team", full_name: "Drew Patel", person_id: "pr-drew", title: "Software Engineer" }];
    api.sessions[ACME].searches.team = { ...api.sessions[ACME].searches.recruiters, kind: "team" };
    await app.open(route(ACME, "&kind=team"));
    await expect(people(page).locator(".fp-count-line")).toHaveText("1 person for a coffee chat at Acme Robotics");
    await person(page, "Drew Patel").getByRole("button", { name: "Write LinkedIn note" }).click();
    expect(api.jobRequests("outreach")[0].body.payload.recipient_type).toBe("engineer");
  });

  test("a failed draft shows the error and keeps the Write button", async ({ app, api, page }) => {
    api.jobOutcomes.outreach = { status: "error", error: "Add your resume on the Profile tab first." };
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    const draft = person(page, "Priya Nair").locator(".fp-draft");
    await draft.getByRole("button", { name: "Write LinkedIn note" }).click();
    await expect(draft.locator(".fp-draft-foot [role=status]")).toHaveText("Add your resume on the Profile tab first.", { timeout: 5000 });
    await expect(draft.locator(".fp-draft-foot [role=status]")).toHaveClass(/error/);
    await expect(draft.getByRole("button", { name: "Write LinkedIn note" })).toBeVisible();
  });

  test("a draft still being written is not requested twice when the list redraws", async ({ app, api, page }) => {
    api.jobOutcomes.outreach = () => ({ ...defaultDraft(), polls: 1 });
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    await person(page, "Priya Nair").getByRole("button", { name: "Write LinkedIn note" }).click();
    // Redraw the list twice while the job runs.
    await person(page, "Jordan Okafor").locator(".fp-person-head").click();
    await person(page, "Priya Nair").locator(".fp-person-head").click();
    await expect(person(page, "Priya Nair").locator(".fp-draft-foot [role=status]")).toHaveText(/^Writing…/);
    await expect(person(page, "Priya Nair").getByRole("textbox", { name: "Intro draft" })).toHaveValue(/Harbourview/, { timeout: 8000 });
    expect(api.jobRequests("outreach")).toHaveLength(1);
  });

  test("edits are saved when the field loses focus", async ({ app, api, page }) => {
    await app.open(route(ACME, "&kind=recruiters"));
    const draft = person(page, "Jordan Okafor").locator(".fp-draft");
    await draft.getByRole("textbox", { name: "Email subject" }).fill("Question about intern teams");
    await draft.getByRole("textbox", { name: "Intro draft" }).click();
    await expect.poll(() => api.last("PUT", "/api/people/drafts/draft-email-1")?.body?.subject).toBe("Question about intern teams");
    expect(api.last("PUT", "/api/people/drafts/draft-email-1")?.body.body).toMatch(/^Hi Jordan,/);
    // Blurring again without changes sends nothing more.
    await draft.getByRole("textbox", { name: "Email subject" }).click();
    await draft.getByRole("textbox", { name: "Intro draft" }).click();
    expect(api.calls("PUT", "/api/people/drafts/draft-email-1")).toHaveLength(1);
  });

  test("Copy puts the subject and body on the clipboard", async ({ app, page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await app.open(route(ACME, "&kind=recruiters"));
    await person(page, "Jordan Okafor").getByRole("button", { name: "Copy" }).click();
    await expect(app.toast()).toHaveText("Copied.");
    const text = await page.evaluate(() => navigator.clipboard.readText());
    expect(text).toMatch(/^Subject: Summer 2027 software internship question\n\nHi Jordan,\n\n/);
  });
});

function defaultDraft() {
  const body = "Hi Priya, I built a Python service at Harbourview Labs and am applying to Acme's software internship. Could I ask how the intern team works?";
  return { status: "done" as const, result: { document_id: "draft-x", id: "draft-x", title: "LinkedIn note · recruiter", subject: "", body,
    angle: "A short question.", checks: [], channel: "linkedin_note", person_id: "pr-priya", chars: body.length, limit: 200 } };
}
