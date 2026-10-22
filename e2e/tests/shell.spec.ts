import { test, expect, fixture } from "../support/test";

// Tests tagged @shell need only the app shell (sidebar, routing, menu, skip link): --grep @shell

test.describe("sidebar and routing", () => {
  test("loads the board by default, with counts and your name in the sidebar @shell", async ({ app, page }) => {
    await app.open();
    await expect(app.section("board")).toBeVisible();
    await expect(app.nav("Internship board")).toHaveAttribute("aria-current", "page");
    await expect(page.locator("#tracker-count")).toHaveText("5");
    await expect(page.locator("#companies-count")).toHaveText("4");
    await expect(page.locator("#who-name")).toHaveText("Sam Rivera");
    await expect(page.locator("#who-avatar")).toHaveText("SR");
    await expect(page.locator("#profile-dot")).toBeHidden();
  });

  test("without a profile the sidebar asks you to set one up @shell", async ({ app, api, page }) => {
    api.profile = fixture("profile-empty.json");
    api.tracker.items = [];
    await app.open();
    await expect(page.locator("#profile-dot")).toBeVisible();
    await expect(page.locator("#profile-dot")).toHaveText("Set up");
    await expect(page.locator("#who-name")).toHaveText("Set up your profile");
    await expect(page.locator("#who-avatar")).toHaveText("?");
    await expect(page.locator("#tracker-count")).toHaveText("");
  });

  test("the board heading shows open internships and company boards", async ({ app, page }) => {
    await app.open();
    await expect(page.locator("#open-total")).toHaveText("11");
    await expect(page.locator("#board-count-text")).toHaveText("3 company job boards");
  });

  test("each sidebar link shows its page and marks itself current @shell", async ({ app, page }) => {
    await app.open();
    const pages: [string, string, RegExp][] = [
      ["Best matches", "board", /#matches$/],
      ["Companies", "companies", /#companies$/],
      ["Tracker", "tracker", /#tracker$/],
      ["Resume tailor", "tool", /#resume$/],
      ["Cover letter", "tool", /#cover$/],
      ["Find people", "people", /#people$/],
      ["My profile", "profile", /#profile$/],
      ["Internship board", "board", /#board$/],
    ];
    for (const [link, section, url] of pages) {
      await app.nav(link).click();
      await expect(page).toHaveURL(url);
      await expect(app.section(section as any)).toBeVisible();
      await expect(app.nav(link)).toHaveAttribute("aria-current", "page");
      await expect(page.locator(".nav [aria-current=page]")).toHaveCount(1);
    }
  });

  test("hash routes open directly, and back/forward move between pages @shell", async ({ app, page }) => {
    await app.open("#tracker");
    await expect(app.section("tracker")).toBeVisible();
    await app.nav("Companies").click();
    await expect(app.section("companies")).toBeVisible();
    await app.nav("My profile").click();
    await expect(app.section("profile")).toBeVisible();

    await page.goBack();
    await expect(app.section("companies")).toBeVisible();
    await expect(app.nav("Companies")).toHaveAttribute("aria-current", "page");
    await page.goBack();
    await expect(app.section("tracker")).toBeVisible();
    await page.goForward();
    await expect(app.section("companies")).toBeVisible();
  });

  test("#matches sorts the board by match, and going back to the board restores newest first", async ({ app, api, page }) => {
    await app.open("#matches");
    await expect(app.nav("Best matches")).toHaveAttribute("aria-current", "page");
    await expect.poll(() => api.listingQueries().at(-1)?.sort).toBe("match");
    await expect(app.dropdown("Sort")).toHaveText("Best match");
    await expect(page.locator(".group-label").first()).toHaveText("Strong match");

    await app.nav("Internship board").click();
    await expect.poll(() => api.listingQueries().at(-1)?.sort).toBe("posted");
    await expect(app.dropdown("Sort")).toHaveText("Newest posted");
  });

  test("#people with listing, kind and add=1 opens the add-person form", async ({ app, page }) => {
    await app.open("#people?listing=simplify%3Aacme-swe-27&kind=recruiters&add=1");
    await expect(page.locator("details.fp-add")).toHaveAttribute("open", "");
    await expect(app.section("people").getByLabel("Name")).toBeVisible();
  });

  test("without a hash, the last page you used opens (view key) @shell", async ({ app, page }) => {
    await app.storage({ view: "companies" });
    await app.open();
    await expect(app.section("companies")).toBeVisible();
    await app.nav("Tracker").click();
    await expect.poll(() => page.evaluate(() => localStorage.getItem("view"))).toBe('"tracker"');
  });

  test("unknown hashes fall back to the board @shell", async ({ app }) => {
    await app.open("#nowhere");
    await expect(app.section("board")).toBeVisible();
    await expect(app.nav("Internship board")).toHaveAttribute("aria-current", "page");
  });
});

test.describe("mobile menu", () => {
  test.use({ viewport: { width: 400, height: 800 } });

  test("below 900px the sidebar opens from the menu button and closes on Escape, scrim or navigation @shell", async ({ app, page }) => {
    await app.open();
    const menu = page.getByRole("button", { name: "Open menu" });
    const sidebar = page.locator("#sidebar");
    await expect(menu).toBeVisible();
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await expect(sidebar).not.toBeInViewport();

    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator("body")).toHaveClass(/nav-open/);
    await expect(sidebar).toBeInViewport();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator("body")).not.toHaveClass(/nav-open/);

    await menu.click();
    await page.locator("#scrim").click({ position: { x: 380, y: 400 } });
    await expect(page.locator("body")).not.toHaveClass(/nav-open/);

    await menu.click();
    await app.nav("Tracker").click();
    await expect(app.section("tracker")).toBeVisible();
    await expect(page.locator("body")).not.toHaveClass(/nav-open/);
    await expect(page.locator("#scrim")).toBeHidden();
  });

  test("the desktop layout has no menu button @shell", async ({ app, page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await app.open();
    await expect(page.getByRole("button", { name: "Open menu" })).toBeHidden();
    await expect(page.locator("#sidebar")).toBeInViewport();
  });
});

test.describe("accessibility basics", () => {
  test("the skip link is the first tab stop and moves focus to the main content @shell", async ({ app, page }) => {
    await app.open("#tracker");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main")).toBeFocused();
    // It stays on the current page.
    await expect(app.section("tracker")).toBeVisible();
    await expect(page).toHaveURL(/#tracker$/);
  });

  test("validation errors from the server are shown as readable text", async ({ app, api }) => {
    api.on("PUT", /^\/api\/tracker\//, { status: 422, json: { detail: [
      { type: "string_pattern_mismatch", loc: ["body", "deadline"], msg: "String should match pattern '^(\\d{4}-\\d{2}-\\d{2})?$'", input: "x" },
    ] } });
    await app.open();
    await app.listing("Northwind Data", "Data Engineering Intern").getByRole("button", { name: "Track" }).click();
    await expect(app.toast()).toHaveText("Request failed: Deadline: String should match pattern '^(\\d{4}-\\d{2}-\\d{2})?$'");
  });

  test("failed requests show a toast with the server's message", async ({ app, api, page }) => {
    api.on("PUT", /^\/api\/tracker\//, { status: 500, json: { detail: "Database is locked" } });
    await app.open();
    await app.listing("Northwind Data", "Data Engineering Intern").getByRole("button", { name: "Track" }).click();
    await expect(app.toast()).toHaveText("Request failed: Database is locked");
    await expect(app.toast()).toBeHidden({ timeout: 7000 });
  });

  test("an unreachable server shows the run.sh toast", async ({ app, api, page }) => {
    await app.open();
    await page.route("**/api/tracker/**", route => route.abort("connectionrefused"));
    await app.listing("Northwind Data", "Data Engineering Intern").getByRole("button", { name: "Track" }).click();
    await expect(app.toast()).toHaveText("Couldn't reach Intern Board. Is ./run.sh still running?");
  });
});
