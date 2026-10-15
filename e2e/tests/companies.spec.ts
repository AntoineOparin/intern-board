import { test, expect, detail } from "../support/test";

const rows = (page: any) => page.locator("#company-rows tr");

test.describe("company watchlist", () => {
  test("shows boards with internships by default, with status, counts and links", async ({ app, api, page }) => {
    await app.open("#companies");
    await expect(page.getByRole("heading", { name: "Company watchlist" })).toBeVisible();
    await expect(page.locator("#company-summary")).toHaveText("Watching 4 of 5 boards");
    await expect(rows(page).locator(".c-name a")).toHaveText(["Northwind Data", "Quillfeather Capital", "Lumen Health"]);

    const northwind = rows(page).filter({ hasText: "Northwind Data" });
    await expect(northwind.locator("td")).toHaveText(["Northwind Data", "greenhouse", "2", "42", "1h ago", ""]);
    await expect(northwind.getByRole("link", { name: "Northwind Data" })).toHaveAttribute("href", "https://job-boards.greenhouse.io/northwind");
    await expect(northwind.getByRole("checkbox", { name: "Watch Northwind Data" })).toBeChecked();
    const quill = rows(page).filter({ hasText: "Quillfeather" });
    await expect(quill.locator(".status-err")).toHaveText("Last check failed");
    await expect(quill.locator(".status-err")).toHaveAttribute("title", "TimeoutError: The read operation timed out");
    await expect(rows(page).filter({ hasText: "Lumen Health" }).locator(".manual")).toHaveText("added by you");
    expect(api.calls("GET", "/api/companies")).toHaveLength(1);
  });

  test("All, Turned off and the name filter", async ({ app, page }) => {
    await app.open("#companies");
    const show = (label: string) => page.locator("#companies-view .segmented label", { hasText: label });
    await show("All").click();
    await expect(rows(page)).toHaveCount(5);
    const polar = rows(page).filter({ hasText: "Polar Labs" });
    await expect(polar.locator(".status-err")).toHaveText("Board not found");
    await expect(polar.locator("td").nth(2)).toHaveText("–");
    await expect(polar.locator("td").nth(3)).toHaveText("–");
    const harbor = rows(page).filter({ hasText: "Old Harbor" });
    await expect(harbor).toHaveClass(/off/);
    await expect(harbor.locator("td").nth(4)).toHaveText("Not yet");

    await show("Turned off").click();
    await expect(rows(page).locator(".c-name a")).toHaveText(["Old Harbor"]);

    await show("All").click();
    await page.getByRole("searchbox", { name: "Filter companies" }).fill("lumen");
    await expect(rows(page).locator(".c-name a")).toHaveText(["Lumen Health"]);
    await page.getByRole("searchbox", { name: "Filter companies" }).fill("polar-labs"); // matches the board token too
    await expect(rows(page).locator(".c-name a")).toHaveText(["Polar Labs"]);
    await page.getByRole("searchbox", { name: "Filter companies" }).fill("zzz");
    await expect(rows(page)).toHaveText(["No companies match."]);
  });

  test("the switch turns a board off or on, then refreshes counts and listings", async ({ app, api, page }) => {
    await app.open("#companies");
    const before = api.requests.length;
    const northwind = rows(page).filter({ hasText: "Northwind Data" });
    await northwind.getByRole("checkbox", { name: "Watch Northwind Data" }).uncheck({ force: true });
    await expect(northwind).toHaveClass(/off/);
    expect(api.last("PATCH", "/api/companies/greenhouse/northwind")?.body).toEqual({ enabled: false });
    await expect.poll(() => api.requests.slice(before).map(r => `${r.method} ${r.path}`))
      .toEqual(expect.arrayContaining(["GET /api/meta", "GET /api/listings"]));

    await page.locator("#companies-view .segmented label", { hasText: "Turned off" }).click();
    const harbor = rows(page).filter({ hasText: "Old Harbor" });
    await harbor.getByRole("checkbox", { name: "Watch Old Harbor" }).check({ force: true });
    expect(api.last("PATCH", "/api/companies/lever/old-harbor")?.body).toEqual({ enabled: true });
    await expect(harbor).not.toHaveClass(/off/);
  });

  test("a failed switch change flips back", async ({ app, api, page }) => {
    api.on("PATCH", /^\/api\/companies\//, detail(404, "Unknown company"));
    await app.open("#companies");
    const checkbox = page.getByRole("checkbox", { name: "Watch Lumen Health" });
    await checkbox.uncheck({ force: true });
    await expect(app.toast()).toHaveText("Request failed: Unknown company");
    await expect(checkbox).toBeChecked();
  });
});

test.describe("add a company by link", () => {
  test("an empty link is rejected without a request", async ({ app, api, page }) => {
    await app.open("#companies");
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page.locator("#add-company-msg")).toHaveText("Paste a link to the company's Greenhouse, Lever or Ashby job board.");
    await expect(page.locator("#add-company-msg")).toHaveClass(/error/);
    await expect(page.getByLabel("Job board link")).toBeFocused();
    expect(api.calls("POST", "/api/companies")).toHaveLength(0);
  });

  test("adds the board, reports what it found and reloads", async ({ app, api, page }) => {
    await app.open("#companies");
    await page.getByLabel("Job board link").fill("  jobs.lever.co/brightpath ");
    await page.getByLabel("Name (optional)").fill("Brightpath");
    const release = api.hold("POST", "/api/companies");
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page.getByRole("button", { name: "Checking board…" })).toBeDisabled();
    release();
    await expect(page.locator("#add-company-msg")).toHaveText("Added Brightpath: 2 matching internships out of 14 open jobs.");
    await expect(page.locator("#add-company-msg")).toHaveClass(/ok/);
    expect(api.last("POST", "/api/companies")?.body).toEqual({ url: "jobs.lever.co/brightpath", name: "Brightpath" });
    await expect(page.getByLabel("Job board link")).toHaveValue("");
    await expect(page.getByRole("button", { name: "Add company" })).toBeEnabled();
    await expect(rows(page).locator(".c-name a")).toContainText(["Brightpath"]);
  });

  test("a blank name is sent as null, and server errors show under the form", async ({ app, api, page }) => {
    api.on("POST", "/api/companies", detail(422, "Paste a Greenhouse, Lever or Ashby link, like jobs.lever.co/company."));
    await app.open("#companies");
    await page.getByLabel("Job board link").fill("example.com/careers");
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page.locator("#add-company-msg")).toHaveText("Paste a Greenhouse, Lever or Ashby link, like jobs.lever.co/company.");
    await expect(page.locator("#add-company")).toHaveClass(/invalid/);
    await expect(app.toast()).toBeHidden(); // quiet: shown in the form only
    expect(api.last("POST", "/api/companies")?.body).toEqual({ url: "example.com/careers", name: null });

    api.on("POST", "/api/companies", detail(404, "No Lever job board called “nobody” exists."));
    await page.getByLabel("Job board link").fill("jobs.lever.co/nobody");
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page.locator("#add-company-msg")).toHaveText("No Lever job board called “nobody” exists.");
  });
});
