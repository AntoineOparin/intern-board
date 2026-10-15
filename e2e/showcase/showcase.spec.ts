// Screenshots and screen recordings for docs/showcase/SHOWCASE.md.
// Run: npx playwright test -c showcase.config.ts, then ../docs/showcase/make-gifs.sh.
// Uses the same mocked API and made-up fixtures as the tests; nothing touches real data.
import { test, expect } from "../support/test";
import type { Page } from "@playwright/test";

const OUT = "../docs/showcase/media";
const ACME = "simplify:acme-swe-27";
const people = (page: Page) => page.locator("#people-view");

async function shot(page: Page, name: string, fullPage = false) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(250);
  await page.evaluate(() => document.getElementById("showcase-cursor")?.style.setProperty("visibility", "hidden"));
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage, animations: "disabled" });
  await page.evaluate(() => document.getElementById("showcase-cursor")?.style.removeProperty("visibility"));
}

const pause = (page: Page, ms = 900) => page.waitForTimeout(ms);

test.beforeEach(async ({ page }) => {
  // Real fonts for nicer images; fixture logos 404 so the app shows its initials fallback.
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, route => route.continue());
  await page.route(/img\.fixture\.test/, route => route.fulfill({ status: 404, body: "" }));
  // A visible cursor, so the recordings show where each click lands.
  await page.addInitScript(() => {
    addEventListener("DOMContentLoaded", () => {
      const dot = document.createElement("div");
      dot.id = "showcase-cursor";
      dot.style.cssText = "position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;"
        + "background:rgba(37,99,235,.28);border:2px solid rgba(37,99,235,.85);pointer-events:none;z-index:2147483647;"
        + "transition:transform .12s ease;transform:translate(-100px,-100px)";
      document.documentElement.appendChild(dot);
      let x = -100, y = -100;
      addEventListener("mousemove", e => { x = e.clientX; y = e.clientY; dot.style.transform = `translate(${x}px,${y}px)`; }, true);
      addEventListener("mousedown", () => { dot.style.transform = `translate(${x}px,${y}px) scale(.7)`; }, true);
      addEventListener("mouseup", () => { dot.style.transform = `translate(${x}px,${y}px)`; }, true);
    });
  });
});

test.afterEach(async ({ page }, info) => {
  const video = page.video();
  await page.close();
  await video?.saveAs(`${OUT}/${info.title}.webm`);
});

test("board", async ({ app, page }) => {
  await app.open();
  await shot(page, "board");
  await pause(page);

  const acme = app.listing("Acme Robotics");
  await acme.locator(".match-badge").click();
  await expect(acme.locator(".match-why")).toBeVisible();
  await shot(page, "board-match-reason");
  await pause(page, 1200);

  const filters = page.locator("#filters");
  await filters.locator(".segmented label", { hasText: "Canada" }).click();
  await pause(page);
  await app.choose("Category", "Software · 5");
  await pause(page);
  await app.dropdown("Sort").click();
  await pause(page, 600);
  await shot(page, "board-dropdown");
  await page.getByRole("option", { name: "Best match", exact: true }).click();
  await pause(page, 1200);
  await shot(page, "board-filtered");

  await page.getByRole("button", { name: /Clear filters/ }).first().click();
  await pause(page);
  await page.locator("body").click({ position: { x: 700, y: 10 } });
  await page.keyboard.press("/");
  await page.keyboard.type("data", { delay: 120 });
  await expect(page.locator("#result-count")).not.toHaveText("11 internships");
  await pause(page, 1200);
  const row = app.listing("Northwind Data", "Data Engineering Intern");
  await row.getByRole("button", { name: "Track" }).click();
  await pause(page, 1500);
});

test("tracker", async ({ app, page }) => {
  await app.open("#tracker");
  await shot(page, "tracker");
  await pause(page);

  await app.card("Acme Robotics").dragTo(app.column("applied"));
  await pause(page, 1200);

  await app.card("Maple Systems").click();
  const drawer = app.drawer();
  await expect(drawer).toBeVisible();
  await pause(page);
  await drawer.locator("label[data-stage=interviewing]").click();
  await drawer.getByLabel("Deadline").fill("2026-10-21");
  await drawer.getByLabel("Notes").fill("");
  await drawer.getByLabel("Notes").pressSequentially("Phone screen booked for Tuesday", { delay: 40 });
  await shot(page, "tracker-drawer");
  await pause(page);
  await drawer.getByRole("button", { name: "Save" }).click();
  await expect(drawer).toBeHidden();
  await pause(page, 1500);
  await shot(page, "tracker-after");
});

test("documents", async ({ app, api, page }) => {
  api.jobOutcomes.tailor_resume = { status: "done", polls: 3, result: { document_id: "doc-resume-new" } };
  await app.open("#resume");
  await shot(page, "documents");
  await pause(page);
  await page.locator("#tool-body").getByRole("button", { name: "Tailor resume" }).click();
  await pause(page, 1500);
  await shot(page, "documents-tailoring");
  await expect(page.locator("#tool-body .docs-msg")).toHaveText(/Resume ready/, { timeout: 15000 });
  await pause(page, 1500);
  await shot(page, "documents-ready");

  await page.goto("./doc.html?id=doc-resume-1");
  await expect(page.locator("#doc-fit")).not.toBeEmpty();
  await pause(page, 1500);
  await shot(page, "doc-resume");
  await page.mouse.wheel(0, 500);
  await pause(page, 1200);

  await page.goto("./doc.html?id=doc-letter-1");
  await expect(page.locator("#doc-fit")).not.toBeEmpty();
  await pause(page, 1200);
  await shot(page, "doc-letter");
  await pause(page, 800);
});

test("people", async ({ app, api, page }) => {
  api.jobOutcomes.outreach = () => ({
    status: "done", polls: 3, result: {
      document_id: "draft-show", id: "draft-show", title: "LinkedIn note · recruiter", subject: "", channel: "linkedin_note",
      person_id: "pr-priya", angle: "Links one shipped project to the team's stack and asks one small question.", checks: [],
      body: "Hi Priya, I built a Python service at Harbourview Labs and I'm applying to Acme's Summer 2027 software internship. Could I ask how the intern team is set up?",
      chars: 160, limit: 200,
    },
  });
  await app.open("#people");
  await shot(page, "people-pick");
  await pause(page);
  await people(page).locator(".fp-job-row").first().click();
  await expect(people(page).locator(".fp-choice[data-kind=recruiters]")).toBeVisible();
  await pause(page, 1200);
  await shot(page, "people-choose");
  await people(page).locator(".fp-choice[data-kind=recruiters]").click();
  await expect(people(page).locator(".fp-count-line")).toBeVisible();
  await pause(page, 1200);
  await shot(page, "people-results");

  const priya = people(page).locator(".fp-person").filter({ hasText: "Priya Nair" });
  await priya.locator(".fp-person-head").click();
  await pause(page);
  await priya.locator(".fp-draft").getByRole("button", { name: "Write LinkedIn note" }).click();
  await pause(page, 1500);
  await expect(priya.getByRole("textbox", { name: "Intro draft" })).toHaveValue(/^Hi Priya/, { timeout: 15000 });
  await pause(page, 600);
  await priya.scrollIntoViewIfNeeded();
  await shot(page, "people-draft");
  await pause(page, 1500);
});

test("profile", async ({ app, api, page }) => {
  api.jobOutcomes.rank_listings = { status: "done", polls: 3, result: { ranked: 40, requested: 40, skipped: 0, batches: 2, failed_batches: 0, error: null, seconds: 52.3 } };
  await app.open("#profile");
  await shot(page, "profile");
  await shot(page, "profile-full", true);
  await pause(page);
  const rank = page.getByRole("button", { name: "Rank top 40 with Claude" });
  await rank.scrollIntoViewIfNeeded();
  await pause(page);
  await rank.click();
  await expect(page.locator(".rank-panel [data-rank-msg]")).toHaveText("Ranked 40 listings in 52s.", { timeout: 15000 });
  await pause(page, 1500);
});

test("companies", async ({ app, page }) => {
  await app.open("#companies");
  await shot(page, "companies");
  await pause(page);
  await page.getByLabel("Job board link").pressSequentially("jobs.lever.co/brightpath", { delay: 40 });
  await page.getByLabel("Name (optional)").pressSequentially("Brightpath", { delay: 40 });
  await page.getByRole("button", { name: "Add company" }).click();
  await expect(page.locator("#add-company-msg")).toHaveText(/Added Brightpath/);
  await pause(page, 1500);
  await shot(page, "companies-added");
});

test("mobile", async ({ app, page }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await app.open();
  await shot(page, "mobile-board");
  await page.getByRole("button", { name: /menu/i }).click();
  await pause(page, 600);
  await shot(page, "mobile-menu");
  await page.keyboard.press("Escape");
  await app.open("#tracker");
  await shot(page, "mobile-tracker");
});
