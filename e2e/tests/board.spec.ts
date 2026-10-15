import { test, expect, NOW, HOUR, DAY, fixture } from "../support/test";

/** Made-up listings for pagination tests. */
function filler(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: `simplify:filler-${i}`, source: "simplify", company: `Filler Company ${String(i).padStart(3, "0")}`,
    title: `Software Intern ${i}`, url: `https://jobs.example.com/filler/${i}`, locations: "Toronto, ON", regions: ["CA"],
    category: "Software", terms: ["Summer 2027"], degrees: ["Bachelor's"], sponsorship: null,
    date_posted: NOW - i * HOUR, first_seen: NOW - i * HOUR, active: 1, posting_key: null, board: null,
    tracked_status: null, match_score: null, match_reason: null, match_method: null,
  }));
}

test.describe("listings", () => {
  test("rows show company, title, locations, tags, source and age, grouped by posting date", async ({ app, page }) => {
    await app.open();
    await expect(page.locator("#result-count")).toHaveText("11 internships");
    await expect(page.locator(".group-label")).toHaveText(["Today", "Yesterday", "This week", "This month", "Date unknown"]);

    const acme = app.listing("Acme Robotics");
    await expect(acme.getByRole("link", { name: "Software Engineer Intern - Summer 2027" }))
      .toHaveAttribute("href", "https://jobs.example.com/acme/swe-27");
    await expect(acme.locator(".loc")).toHaveText("Toronto, ON · Waterloo, ON +1");
    await expect(acme.locator(".loc")).toHaveAttribute("title", "Toronto, ON\nWaterloo, ON\nMontreal, QC");
    await expect(acme.locator(".age")).toHaveText("2h ago");
    await expect(acme.locator(".l-meta .tag")).toHaveText(["Software", "Summer 2027"]);
    await expect(acme.getByRole("link", { name: "Apply ↗" })).toHaveAttribute("target", "_blank");

    const direct = app.listing("Northwind Data", "Data Engineering Intern");
    await expect(direct.locator(".tag.direct")).toHaveText("Direct");
    const zapply = app.listing("Lumen Health", "Backend Developer Intern");
    await expect(zapply.getByRole("link", { name: "via Zapply" })).toHaveAttribute("href", "https://github.com/zapplyjobs/Internships-2027");
    await expect(zapply.locator(".tag.warn")).toHaveText("Offers Sponsorship");
    await expect(app.listing("Maple Systems").getByRole("link", { name: "via Canadian Tech Internships" })).toBeVisible();
    await expect(app.listing("Polar Labs").getByRole("link", { name: "via Canada Tech Internships" })).toBeVisible();
    await expect(app.listing("Quillfeather Capital").locator(".tag.warn")).toHaveText("U.S. Citizenship is Required");
    await expect(app.listing("Birch & Co").locator(".tag.warn")).toHaveCount(0); // "Other" sponsorship isn't shown
  });

  test("sorting by date added, company and match changes the groups", async ({ app, api, page }) => {
    await app.open();
    await app.choose("Sort", "Recently added here");
    await expect.poll(() => api.listingQueries().at(-1)?.sort).toBe("added");
    await expect(page.locator(".group-label")).toHaveText(["Today", "Yesterday", "This week", "This month"]);

    await app.choose("Sort", "Company A–Z");
    await expect(page.locator(".group-label")).toHaveText(["A", "B", "J", "L", "M", "N", "O", "P", "Q"]);

    await app.choose("Sort", "Best match");
    await expect(page.locator(".group-label")).toHaveText(["Strong match", "Possible match", "Weak match", "Not scored"]);
    await expect(page.locator(".group-wrap").first().locator(".listing .l-company"))
      .toContainText(["Acme Robotics", "Orbit Analytics"]);
  });

  test("match badges show the score and reveal the reason on click", async ({ app, page }) => {
    await app.open();
    const acme = app.listing("Acme Robotics");
    const badge = acme.getByRole("button", { name: "Strong match, 82 out of 100, scored by Claude. Show why." });
    await expect(badge).toHaveText("82");
    await expect(badge).toHaveClass(/strong/);
    await expect(app.listing("Northwind Data", "Data Engineering Intern").locator(".match-badge")).toHaveClass(/ok/);
    await expect(app.listing("Quillfeather Capital").locator(".match-badge")).toHaveClass(/weak/);
    await expect(app.listing("Maple Systems").locator(".match-badge")).toHaveCount(0);

    await badge.click();
    await expect(badge).toHaveAttribute("aria-expanded", "true");
    await expect(acme.locator(".match-why")).toHaveText(/Python and robotics projects match the team's stack\.\s+· Claude, 82\/100/);
    await badge.click();
    await expect(badge).toHaveAttribute("aria-expanded", "false");
    await expect(acme.locator(".match-why")).toHaveCount(0);
  });

  test("Best match without a resume shows a note linking to the profile", async ({ app, api, page }) => {
    api.profile = fixture("profile-empty.json");
    api.ranking = fixture("ranking-status.json").no_profile;
    await app.open("#matches");
    await expect(page.locator("#rank-note")).toHaveText(/Best match needs your resume\.\s+Add it on the Profile tab\s+and every listing gets a score\./);
    await page.locator("#rank-note").getByRole("link", { name: "Add it on the Profile tab" }).click();
    await expect(app.section("profile")).toBeVisible();
  });

  test("no results shows the empty state, and its link clears the filters", async ({ app, api, page }) => {
    await app.open();
    await page.getByRole("searchbox", { name: "Search listings" }).fill("zzzz");
    await expect(page.getByText("No listings match these filters.")).toBeVisible();
    await expect(page.locator("#result-count")).toHaveText("0 internships");
    await page.getByRole("button", { name: "clear the filters" }).click();
    await expect(page.locator("#result-count")).toHaveText("11 internships");
    await expect(page.getByRole("searchbox", { name: "Search listings" })).toHaveValue("");
    expect(api.listingQueries().at(-1)).not.toHaveProperty("q");
  });

  test("Show more loads the next page of 50 and hides when everything is shown", async ({ app, api, page }) => {
    api.listings = filler(120);
    await app.open();
    await expect(page.locator("#result-count")).toHaveText("120 internships");
    await expect(page.locator("#listings .listing")).toHaveCount(50);
    expect(api.listingQueries()[0]).toMatchObject({ offset: "0", limit: "50", sort: "posted" });

    await page.getByRole("button", { name: "Show more" }).click();
    await expect(page.locator("#listings .listing")).toHaveCount(100);
    await page.getByRole("button", { name: "Show more" }).click();
    await expect(page.locator("#listings .listing")).toHaveCount(120);
    await expect(page.getByRole("button", { name: "Show more" })).toBeHidden();
    expect(api.listingQueries().map(q => q.offset)).toEqual(["0", "50", "100"]);
  });

  test("changing filters never loads a stray next page or gets stuck loading", async ({ app, api, page }) => {
    // Enough listings that the infinite-scroll sentinel matters; every third one is in Canada.
    api.listings = filler(150).map((l, i) => ({ ...l, regions: i % 3 ? ["US"] : ["CA"] }));
    await app.open();
    await expect(page.locator("#listings .listing")).toHaveCount(50);
    const regions = page.locator("#filters .segmented label");
    for (const [label, count] of [["US", "100 internships"], ["Canada", "50 internships"], ["All", "150 internships"], ["US", "100 internships"], ["All", "150 internships"]]) {
      const before = api.listingQueries().length;
      await regions.filter({ hasText: label }).first().click();
      await expect(page.locator("#result-count")).toHaveText(count);
      await expect(page.locator("#listings .skeleton")).toHaveCount(0);
      await expect(page.locator("#listings .listing")).toHaveCount(50);
      // Only the first page of the new filter was asked for.
      expect(api.listingQueries().slice(before).map(q => q.offset)).toEqual(["0"]);
    }
  });

  test("scrolling near the end loads more automatically", async ({ app, api, page }) => {
    api.listings = filler(80);
    await app.open();
    await expect(page.locator("#listings .listing")).toHaveCount(50);
    await page.locator("#listings .listing").nth(45).scrollIntoViewIfNeeded();
    await expect(page.locator("#listings .listing")).toHaveCount(80);
    expect(api.listingQueries().map(q => q.offset)).toEqual(["0", "50"]);
  });
});

test.describe("filters", () => {
  test("/ focuses search, and typing sends q after a short pause", async ({ app, api, page }) => {
    await app.open();
    const search = page.getByRole("searchbox", { name: "Search listings" });
    await page.locator("body").click({ position: { x: 700, y: 10 } });
    await page.keyboard.press("/");
    await expect(search).toBeFocused();
    await expect(search).toHaveValue("");
    await page.keyboard.type("lumen");
    await expect.poll(() => api.listingQueries().at(-1)?.q).toBe("lumen");
    await expect(page.locator("#result-count")).toHaveText("2 internships");
    // Typing is debounced: one query for the whole word, not one per letter.
    expect(api.listingQueries().filter(q => q.q).length).toBe(1);
  });

  test("/ does nothing while typing in another field or on another page", async ({ app, page }) => {
    await app.open("#companies");
    await page.keyboard.press("/");
    await expect(page.locator("#filters input[name=q]")).not.toBeFocused();
    await page.getByRole("searchbox", { name: "Filter companies" }).fill("a/b");
    await expect(page.getByRole("searchbox", { name: "Filter companies" })).toHaveValue("a/b");
  });

  test("region, category, term, degree, source, sort and toggles are sent to /api/listings", async ({ app, api, page }) => {
    await app.open();
    const filters = page.locator("#filters");
    await filters.locator(".segmented label", { hasText: "Canada" }).click();
    await expect.poll(() => api.listingQueries().at(-1)?.region).toBe("CA");
    await expect(filters.locator(".segmented label", { hasText: "Canada" })).toHaveText("Canada 5");
    await expect(filters.locator(".segmented label").first()).toHaveText("All 11"); // every segment shows a count

    await app.choose("Category", "Software · 5");
    await expect.poll(() => api.listingQueries().at(-1)?.category).toBe("Software");
    await app.choose("Term", "Summer 2027 · 8");
    await expect.poll(() => api.listingQueries().at(-1)?.term).toBe("Summer 2027");
    await app.choose("Degree", "Bachelor's · 9");
    await expect.poll(() => api.listingQueries().at(-1)?.degree).toBe("Bachelor's");
    await app.choose("Source", "SimplifyJobs list");
    await expect.poll(() => api.listingQueries().at(-1)?.source).toBe("simplify");
    await app.choose("Sort", "Company A–Z");
    await expect.poll(() => api.listingQueries().at(-1)?.sort).toBe("company");
    await filters.getByText("Hide tracked").click();
    await expect.poll(() => api.listingQueries().at(-1)?.hide_tracked).toBe("true");

    expect(api.listingQueries().at(-1)).toEqual({
      offset: "0", limit: "50", sort: "company", region: "CA", category: "Software", term: "Summer 2027",
      degree: "Bachelor's", source: "simplify", hide_tracked: "true",
    });
    await expect(page.locator("#result-count")).toHaveText("0 internships"); // Acme and Juniper are tracked
  });

  test("New only sends since = the visit baseline", async ({ app, api, page }) => {
    await app.storage({ lastActive: NOW - 6 * HOUR, baseline: NOW - 2 * DAY });
    await app.open();
    await page.locator("#filters").getByText("New only").click();
    await expect.poll(() => api.listingQueries().at(-1)?.since).toBe(String(NOW - 6 * HOUR));
    await expect(page.locator("#result-count")).toHaveText("2 internships");
  });

  test("filters are saved, restored on reload, and cleared with Clear filters", async ({ app, api, page }) => {
    await app.open();
    const clear = page.getByRole("button", { name: "Clear filters" });
    await expect(clear).toBeHidden();
    await app.choose("Category", "AI/ML/Data · 3");
    await page.locator("#filters .segmented label", { hasText: "US" }).click();
    await page.getByRole("searchbox", { name: "Search listings" }).fill("data");
    await expect.poll(() => api.listingQueries().at(-1)?.q).toBe("data");
    await expect(clear).toBeVisible();
    expect(JSON.parse((await page.evaluate(() => localStorage.getItem("filters")))!)).toEqual({
      q: "data", region: "US", category: "AI/ML/Data", term: "", degree: "", source: "", sort: "posted",
      new_only: false, hide_tracked: false,
    });

    await app.reload();
    await expect.poll(() => api.listingQueries().at(-1)).toMatchObject({ q: "data", region: "US", category: "AI/ML/Data" });
    await expect(page.getByRole("searchbox", { name: "Search listings" })).toHaveValue("data");
    await expect(app.dropdown("Category")).toHaveText("AI/ML/Data · 3");
    await expect(page.locator("#filters input[name=region][value=US]")).toBeChecked();
    await expect(clear).toBeVisible();

    await clear.click();
    await expect.poll(() => api.listingQueries().at(-1)).toEqual({ offset: "0", limit: "50", sort: "posted" });
    await expect(app.dropdown("Category")).toHaveText("All categories");
    await expect(page.locator("#filters input[name=region][value='']")).toBeChecked();
    await expect(clear).toBeHidden();
  });

  test("filters saved by an earlier version are restored, including options that load later", async ({ app, api, page }) => {
    await app.storage({ filters: { q: "", region: "", category: "Hardware", term: "Fall 2026", degree: "", source: "negarprh", sort: "added", new_only: false, hide_tracked: false } });
    await app.open();
    await expect.poll(() => api.listingQueries().at(-1)).toMatchObject({ category: "Hardware", term: "Fall 2026", source: "negarprh", sort: "added" });
    await expect(app.dropdown("Category")).toHaveText("Hardware · 1");
    await expect(app.dropdown("Term")).toHaveText("Fall 2026 · 2");
    await expect(app.dropdown("Source")).toHaveText("Canadian Tech Internships");
    await expect(page.locator("#result-count")).toHaveText("1 internship");
  });
});

test.describe("stats strip", () => {
  test("shows counts from /api/meta, the tracker and the new-since-visit query", async ({ app, page }) => {
    await app.open();
    await expect(page.locator("[data-stat=CA] .stat-value")).toHaveText("5");
    await expect(page.locator("[data-stat=board] .stat-value")).toHaveText("3");
    await expect(page.locator("[data-stat=due] .stat-value")).toHaveText("2");
    await expect(page.locator("[data-stat=new] .stat-value")).toHaveText("0");
  });

  test("New, Canada and Direct toggle their filter and highlight; Deadlines opens the tracker", async ({ app, api, page }) => {
    await app.open();
    const stat = (label: string) => page.getByRole("button", { name: new RegExp(label) });

    await stat("In Canada").click();
    await expect.poll(() => api.listingQueries().at(-1)?.region).toBe("CA");
    await expect(stat("In Canada")).toHaveClass(/active/);
    await stat("In Canada").click();
    await expect.poll(() => api.listingQueries().at(-1)?.region).toBeUndefined();
    await expect(stat("In Canada")).not.toHaveClass(/active/);

    await stat("Direct from companies").click();
    await expect.poll(() => api.listingQueries().at(-1)?.source).toBe("board");
    await expect(stat("Direct from companies")).toHaveClass(/active/);
    await expect(app.dropdown("Source")).toHaveText("Company boards");

    await stat("New since last visit").click();
    await expect.poll(() => api.listingQueries().at(-1)?.since).toBe(String(NOW));
    await expect(stat("New since last visit")).toHaveClass(/active/);
    await expect(page.locator("#filters input[name=new_only]")).toBeChecked();

    await stat("Deadlines this week").click();
    await expect(page).toHaveURL(/#tracker$/);
    await expect(app.section("tracker")).toBeVisible();
  });
});

test.describe("tracking from the board", () => {
  test("Track saves the listing, then the button shows its stage and opens the side panel", async ({ app, api, page }) => {
    await app.open();
    const row = app.listing("Northwind Data", "Data Engineering Intern");
    await row.getByRole("button", { name: "Track" }).click();
    const put = api.last("PUT", "/api/tracker/board:greenhouse:northwind:4401");
    expect(put?.body).toEqual({ status: "saved", position: NOW });
    await expect(row.locator(".track-btn")).toHaveText("saved");
    await expect(page.locator("#tracker-count")).toHaveText("6");

    await row.getByRole("button", { name: "saved" }).click();
    await expect(app.drawer()).toBeVisible();
    await expect(app.drawer().locator("#drawer-title")).toHaveText("Data Engineering Intern");
    await expect(app.drawer().getByRole("radio", { name: "saved" })).toBeChecked();
  });

  test("tracked listings show their stage instead of Track", async ({ app }) => {
    await app.open();
    await expect(app.listing("Acme Robotics").locator(".track-btn")).toHaveText("saved");
    await expect(app.listing("Orbit Analytics").locator(".track-btn")).toHaveText("applied");
    await expect(app.listing("Juniper Shield").locator(".track-btn")).toHaveText("interviewing");
    await expect(app.listing("Polar Labs").getByRole("button", { name: "Track" })).toBeVisible();
  });
});

test.describe("refresh", () => {
  test("shows the busy state, then the number of new internships and 'Updated just now'", async ({ app, api, page }) => {
    await app.open();
    const sync = page.locator("#sync-status");
    await expect(sync).toHaveText("Updated 10m ago");
    await expect(sync).toHaveClass(/ok/);

    const release = api.hold("POST", "/api/refresh");
    const button = page.locator("#refresh-btn");
    await button.click();
    await expect(button).toBeDisabled();
    await expect(button).toHaveText("Refreshing…");
    await expect(button).toHaveClass(/spinning/);
    await expect(page.locator("#refresh-result")).toHaveText("Checking every source, about 30–60 seconds.");
    await expect(sync).toHaveText("Checking sources…");
    await expect(sync).toHaveClass(/busy/);
    const before = api.requests.length;

    release();
    await expect(page.locator("#refresh-result")).toHaveText("3 new internships");
    await expect(page.locator("#refresh-result")).toHaveClass("ok");
    await expect(sync).toHaveText("Updated just now");
    await expect(button).toBeEnabled();
    await expect(button).toHaveText("Refresh");
    const after = api.requests.slice(before).map(r => `${r.method} ${r.path}${r.query.limit === "1" ? " (new count)" : ""}`);
    expect(after).toEqual(expect.arrayContaining(["GET /api/meta", "GET /api/listings", "GET /api/listings (new count)"]));
  });

  test("result text for one, none, an overlapping refresh, and a failure", async ({ app, api, page }) => {
    await app.open();
    const result = page.locator("#refresh-result");
    const button = page.locator("#refresh-btn");

    api.refreshResult = { status: "ok", new: 1 };
    await button.click();
    await expect(result).toHaveText("1 new internship");

    api.refreshResult = { status: "ok", new: 0 };
    await button.click();
    await expect(result).toHaveText("No new internships since the last check.");
    await expect(result).toHaveClass("muted");

    api.refreshResult = { status: "error", error: "SimplifyJobs returned HTTP 503" };
    await button.click();
    await expect(app.toast()).toHaveText("Refresh failed: SimplifyJobs returned HTTP 503");
    await expect(result).toHaveText("");
    await expect(button).toBeEnabled();
  });

  test("when a refresh is already running, the button keeps spinning until it finishes", async ({ app, api, page }) => {
    await app.open();
    const button = page.locator("#refresh-btn");
    const result = page.locator("#refresh-result");
    api.refreshResult = { status: "already_running" };
    await button.click();
    await expect(result).toHaveText("Another refresh is already running. Waiting for it to finish…");
    await expect(button).toBeDisabled();
    await expect(button).toHaveClass(/spinning/);
    await expect(button).toHaveText("Refreshing…");
    await expect(page.locator("#sync-status")).toHaveText("Checking sources…");
    // Still going after a poll or two.
    await page.waitForTimeout(2500);
    await expect(button).toHaveClass(/spinning/);

    const before = api.listingQueries().length;
    api.meta.last_refresh = NOW + 1; // the server's refresh finishes
    await expect(result).toHaveText("Refresh finished. The board is up to date.", { timeout: 5000 });
    await expect(result).toHaveClass("ok");
    await expect(button).toBeEnabled();
    await expect(button).not.toHaveClass(/spinning/);
    await expect(button).toHaveText("Refresh");
    expect(api.listingQueries().length).toBeGreaterThan(before); // the board reloaded
  });

  test("a refresh already running that fails shows the error", async ({ app, api, page }) => {
    await app.open();
    api.refreshResult = { status: "already_running" };
    await page.locator("#refresh-btn").click();
    await expect(page.locator("#refresh-result")).toHaveText("Another refresh is already running. Waiting for it to finish…");
    api.meta.last_error = "HTTPError: 502";
    await expect(app.toast()).toHaveText("Refresh failed: HTTPError: 502", { timeout: 5000 });
    await expect(page.locator("#refresh-btn")).toBeEnabled();
  });

  test("the spinner still turns with Reduce motion on", async ({ app, api, page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await app.open();
    const release = api.hold("POST", "/api/refresh");
    await page.locator("#refresh-btn").click();
    const duration = await page.locator("#refresh-btn .icon").evaluate(el => getComputedStyle(el).animationDuration);
    expect(duration).toBe("2s");
    release();
  });

  test("a failed last refresh and the first import show in the sync status", async ({ app, api, page }) => {
    api.meta.last_error = "HTTPError: 502";
    await app.open();
    await expect(page.locator("#sync-status")).toHaveText("Last refresh failed");
    await expect(page.locator("#sync-status")).toHaveAttribute("title", "HTTPError: 502");
  });

  test("on the first run the page waits for the import to finish", async ({ app, api, page }) => {
    api.meta.last_refresh = 0;
    let metaCalls = 0;
    api.on("GET", "/api/meta", (_req, api) => {
      if (++metaCalls === 2) api.meta.last_refresh = NOW;
      return { json: api.meta };
    });
    await page.goto("./");
    await expect(page.locator("#sync-status")).toHaveText("First import…");
    await expect(page.locator("#sync-status")).toHaveText("Updated just now", { timeout: 6000 });
    await app.ready();
    expect(metaCalls).toBeGreaterThanOrEqual(2);
  });
});

test.describe("new since last visit", () => {
  test("first visit ever: nothing is new and the baseline is now", async ({ app, api, page }) => {
    await app.open();
    await expect(page.locator("[data-stat=new] .stat-value")).toHaveText("0");
    await expect(page.locator(".tag.new")).toHaveCount(0);
    expect(api.last("GET", "/api/listings")).toBeTruthy();
    expect(api.calls("GET", "/api/listings").find(r => r.query.limit === "1")?.query.since).toBe(String(NOW));
    expect(await page.evaluate(() => [localStorage.getItem("baseline"), localStorage.getItem("lastActive")]))
      .toEqual([String(NOW), String(NOW)]);
  });

  test("a new session counts from the end of the previous one, and reloads keep that baseline", async ({ app, api, page }) => {
    await app.storage({ lastActive: NOW - 6 * HOUR, baseline: NOW - 3 * DAY });
    await app.open();
    await expect(page.locator("[data-stat=new] .stat-value")).toHaveText("2");
    await expect(page.locator(".listing:has(.tag.new) .l-company")).toContainText(["Acme Robotics", "Northwind Data"]);
    await expect(page.locator(".tag.new")).toHaveCount(2);
    expect(await page.evaluate(() => localStorage.getItem("baseline"))).toBe(String(NOW - 6 * HOUR));

    await app.reload();
    await expect(page.locator("[data-stat=new] .stat-value")).toHaveText("2");
    expect(api.calls("GET", "/api/listings").filter(r => r.query.limit === "1").map(r => r.query.since))
      .toEqual([String(NOW - 6 * HOUR), String(NOW - 6 * HOUR)]);
  });

  test("coming back within 30 minutes stays in the same session", async ({ app, page }) => {
    await app.storage({ lastActive: NOW - 10 * 60, baseline: NOW - DAY - 4 * HOUR });
    await app.open();
    await expect(page.locator("[data-stat=new] .stat-value")).toHaveText("3");
    expect(await page.evaluate(() => localStorage.getItem("baseline"))).toBe(String(NOW - DAY - 4 * HOUR));
  });

  test("the legacy lastVisit key is used once and removed", async ({ app, page }) => {
    await app.storage({ lastVisit: NOW - 6 * HOUR });
    await app.open();
    await expect(page.locator("[data-stat=new] .stat-value")).toHaveText("2");
    expect(await page.evaluate(() => [localStorage.getItem("lastVisit"), localStorage.getItem("baseline")]))
      .toEqual([null, String(NOW - 6 * HOUR)]);
  });
});
