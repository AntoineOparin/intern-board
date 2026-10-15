// Optional screenshots for comparing the old and new frontends by eye (not pixel-matched).
// Run with VISUAL=1; images go to e2e/screenshots/<SHOTS or "current">/.
import { test, expect } from "../support/test";

const DIR = `screenshots/${process.env.SHOTS || "current"}`;
const PAGES: [string, string][] = [
  ["board", "#board"], ["matches", "#matches"], ["tracker", "#tracker"], ["companies", "#companies"],
  ["resume", "#resume"], ["people-pick", "#people"], ["people-choose", "#people?listing=simplify%3Aacme-swe-27"],
  ["people-results", "#people?listing=simplify%3Aacme-swe-27&kind=recruiters"], ["profile", "#profile"],
];

test.describe("screenshots", () => {
  test.skip(!process.env.VISUAL, "Set VISUAL=1 to take screenshots");

  for (const width of [1440, 400]) {
    test(`all pages at ${width}px`, async ({ app, page }) => {
      await page.setViewportSize({ width, height: 900 });
      for (const [name, hash] of PAGES) {
        await app.open(hash);
        await page.evaluate(() => document.fonts.ready);
        await page.screenshot({ path: `${DIR}/${name}-${width}.png`, fullPage: true, animations: "disabled" });
      }
      await app.open("#tracker");
      await app.card("Acme Robotics").click();
      await expect(app.drawer()).toBeVisible();
      await page.screenshot({ path: `${DIR}/drawer-${width}.png`, animations: "disabled" });
      for (const id of ["doc-resume-1", "doc-letter-1"]) {
        await page.goto(`./doc.html?id=${id}`);
        await expect(page.locator("#doc-fit")).not.toBeEmpty();
        await page.screenshot({ path: `${DIR}/${id}-${width}.png`, fullPage: true, animations: "disabled" });
      }
    });
  }
});
