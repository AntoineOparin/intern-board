// doc.html: the printable, editable resume or cover letter.
import { test, expect, fixture } from "../support/test";

test.describe("resume page", () => {
  test("renders the resume, its notes and the one-page check", async ({ app, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    await expect(page).toHaveTitle("Sam Rivera – Resume – Acme Robotics");
    await expect(page.locator("#doc-kind")).toHaveText("Resume");
    await expect(page.locator("#doc-for")).toHaveText("Software Engineer Intern - Summer 2027 · Acme Robotics");
    const sheet = page.locator("#sheet");
    await expect(sheet.locator(".r-name")).toHaveText("Sam Rivera");
    await expect(sheet.locator(".r-contact")).toHaveText("Toronto, ON|555-0142|sam.rivera@example.com|github.com/sam-rivera-example");
    await expect(sheet.locator(".r-section h2")).toHaveText(["Education", "Experience", "Projects", "Skills"]);
    await expect(sheet.locator(".r-detail").last()).toHaveText("Awards: Dean's list 2024");
    await expect(sheet.locator(".r-section").nth(1).locator("li")).toHaveText([
      "Built a Python service that cut report generation from 40 minutes to 6 minutes.",
      "Wrote integration tests for the service's REST endpoints.",
    ]);
    await expect(sheet.locator(".r-skills p")).toHaveText(["Languages: Python, Go, TypeScript", "Tools: Git, Docker"]);

    const notes = page.locator("#doc-notes");
    await expect(notes.locator("h2")).toHaveText("Tailoring notes");
    await expect(notes.locator("h3")).toHaveText(["Emphasised", "Gaps in the posting"]);
    await expect(page.locator("#doc-fit")).toHaveText("Fits on one page");
    await expect(page.locator("#doc-fit")).toHaveClass(/ok/);
    await expect(page.getByRole("button", { name: "Save edits" })).toBeDisabled();
  });

  test("text is edited in place, Enter finishes a line, and Save sends the cleaned content", async ({ app, api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bullets = page.locator("#sheet .r-section").nth(1).locator("li");
    await bullets.nth(0).click();
    await page.keyboard.press("ControlOrMeta+A"); // selects the line's text only
    await page.keyboard.type("Built a Python service that cut report generation from 40 minutes to 6 minutes. Used by 3 teams.");
    await page.keyboard.press("Enter");
    await expect(bullets.nth(0)).not.toBeFocused();
    await expect(bullets.nth(0)).toHaveText("Built a Python service that cut report generation from 40 minutes to 6 minutes. Used by 3 teams.");
    await expect(page.locator("#doc-msg")).toHaveText("Unsaved edits");
    const save = page.getByRole("button", { name: "Save edits" });
    await expect(save).toBeEnabled();

    // An emptied bullet is dropped when saving.
    await bullets.nth(1).click();
    await page.keyboard.press("ControlOrMeta+A");
    await page.keyboard.press("Backspace");
    await save.click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    await expect(save).toBeDisabled();
    const sent = api.last("PUT", "/api/documents/doc-resume-1")?.body.content;
    expect(sent.experience[0].bullets).toEqual(["Built a Python service that cut report generation from 40 minutes to 6 minutes. Used by 3 teams."]);
    expect(sent.header).toEqual(fixture("documents.json").resume.content.header);
    await expect(bullets).toHaveCount(1);
  });

  test("a failed save keeps the edits and shows the error", async ({ app, api, page }) => {
    api.on("PUT", "/api/documents/doc-resume-1", { status: 422, json: { detail: "The document is missing: skills." } });
    await page.goto("./doc.html?id=doc-resume-1");
    await page.locator("#sheet .r-name").click();
    await page.keyboard.type("x");
    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("The document is missing: skills.");
    await expect(page.locator("#doc-msg")).toHaveClass(/error/);
    await expect(page.getByRole("button", { name: "Save edits" })).toBeEnabled();
  });

  test("a resume too long for one page says so", async ({ app, api, page }) => {
    const doc = api.docs["doc-resume-1"];
    const bullet = "Built and maintained a service with a long description that wraps onto a second printed line on the page.";
    doc.content.experience = Array.from({ length: 8 }, (_, i) => ({ ...doc.content.experience[0], organization: `Company ${i}`, bullets: Array(5).fill(bullet) }));
    await page.goto("./doc.html?id=doc-resume-1");
    await expect(page.locator("#doc-fit")).toHaveText("Runs past one page even at 10pt. Shorten a few lines or remove an entry.");
    await expect(page.locator("#doc-fit")).toHaveClass(/error/);
  });

  test("Download PDF opens the print dialog with a hint", async ({ page }) => {
    await page.addInitScript(() => { (window as any).__printed = 0; window.print = () => { (window as any).__printed++; }; });
    await page.goto("./doc.html?id=doc-resume-1");
    await page.getByRole("button", { name: "Download PDF" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Choose “Save as PDF” as the destination");
    expect(await page.evaluate(() => (window as any).__printed)).toBe(1);
  });

  test("Back without a previous page goes to the tracker", async ({ app, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    await page.getByRole("button", { name: "← Back" }).click();
    await expect(page).toHaveURL(/\/#tracker$/);
    await app.ready();
    await expect(app.section("tracker")).toBeVisible();
  });
});

test.describe("cover letter page", () => {
  test("renders the letter with tone, word count and warnings", async ({ page }) => {
    await page.goto("./doc.html?id=doc-letter-1");
    await expect(page.locator("#doc-kind")).toHaveText("Cover letter");
    const sheet = page.locator("#sheet");
    await expect(sheet.locator(".doc-l-greeting")).toHaveText("Dear Acme Robotics hiring team,");
    await expect(sheet.locator(".doc-l-body > p")).toHaveCount(6);
    await expect(sheet.locator(".doc-l-signature")).toHaveText("Sam Rivera");
    const notes = page.locator("#doc-notes");
    await expect(notes.locator("h2")).toHaveText("Letter notes");
    const words = fixture("documents.json").letter.content.paragraphs.join(" ").split(/\s+/).length;
    await expect(notes.locator("p")).toHaveText([
      "Your profile has changed since this was written.",
      "Written without the job description, from the title and company only.",
      `Formal tone · ${words} words`,
    ]);
    await expect(notes.locator("h3")).toHaveText(["Check before sending", "Draws on"]);
  });
});

test.describe("errors", () => {
  test("a link without an id", async ({ page }) => {
    await page.goto("./doc.html");
    await expect(page.getByText("No document id in the link.")).toBeVisible();
    await expect(page.getByText("Open documents from a listing in your tracker.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save edits" })).toBeHidden();
    await expect(page.getByRole("button", { name: "Download PDF" })).toBeHidden();
  });

  test("a document that no longer exists", async ({ page }) => {
    await page.goto("./doc.html?id=gone");
    await expect(page.getByText("That document doesn't exist.")).toBeVisible();
  });
});
