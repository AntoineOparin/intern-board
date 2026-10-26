// doc.html: the printable, editable resume or cover letter.
import type { Locator } from "@playwright/test";
import { test, expect, fixture } from "../support/test";
import type { MockApi } from "../support/mock-api";

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

  test("a bullet can be swapped for another phrasing of its point, or for an unused point", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bullets = page.locator("#sheet .r-section").nth(1).locator("li.r-li");
    await expect(page.locator("#doc-notes p").last()).toHaveText("Hover a bullet and use the swap button to pick another phrasing from your profile.");
    const swap = bullets.nth(0).getByRole("button", { name: "Swap this bullet for another phrasing" });
    await bullets.nth(0).hover();
    await swap.click();
    const menu = page.getByRole("group", { name: "Other phrasings" });
    await expect(menu.locator("h4")).toHaveText(["Other phrasings of this point", "Other points from this entry"]);
    await expect(menu.getByRole("button")).toHaveText([
      "Cut report generation from 40 minutes to 6 minutes by building a Python service.",
      "Reviewed pull requests from two other interns.",
    ]);
    await expect(menu.getByRole("button").first()).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(swap).toBeFocused();

    await swap.click();
    await menu.getByRole("button", { name: "Cut report generation from 40 minutes to 6 minutes by building a Python service." }).click();
    await expect(bullets.nth(0)).toHaveText("Cut report generation from 40 minutes to 6 minutes by building a Python service.");
    await expect(page.locator("#doc-msg")).toHaveText("Unsaved edits");
    await bullets.nth(1).getByRole("button", { name: "Swap this bullet for another phrasing" }).click();
    await expect(menu.locator("h4")).toHaveText(["Other points from this entry"]);
    await menu.getByRole("button", { name: "Reviewed pull requests from two other interns." }).click();
    await expect(bullets.nth(1)).toHaveText("Reviewed pull requests from two other interns.");
    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    const sent = api.last("PUT", "/api/documents/doc-resume-1")?.body.content.experience[0];
    expect(sent.source_id).toBe("e-harbour");
    expect(sent.refs).toEqual([{ point_id: "p-report", phrasing: 1 }, { point_id: "p-review", phrasing: 0 }]);
  });

  test("a document written before points, or a profile that can't be read, has no swap buttons", async ({ api, page }) => {
    delete api.docs["doc-resume-1"].content.experience[0].refs;
    await page.goto("./doc.html?id=doc-resume-1");
    await expect(page.locator("#sheet .r-section").nth(1).locator("li")).toHaveCount(2);
    await expect(page.locator("#sheet .r-swap")).toHaveCount(0); // the project's only point has one phrasing
    await expect(page.locator("#doc-notes p")).toHaveText(["Hover a bullet and use the swap button to pick another phrasing from your profile."]);

    api.docs["doc-resume-1"] = fixture("documents.json").resume;
    api.on("GET", "/api/profile", { status: 500, json: { detail: "boom" } });
    await page.goto("./doc.html?id=doc-resume-1");
    await expect(page.locator("#sheet .r-section").nth(1).locator("li")).toHaveCount(2);
    await expect(page.locator("#sheet .r-swap")).toHaveCount(0);
    await expect(page.locator("#doc-notes p")).toHaveCount(0);
    await expect(page.locator(".toast")).toHaveCount(0);
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

/** Selects `text` inside a field, as a user would by dragging over it. */
async function selectText(field: Locator, text: string) {
  await field.evaluate((el, text) => {
    (el as HTMLElement).focus();
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const i = n.textContent!.indexOf(text);
      if (i < 0) continue;
      const r = document.createRange();
      r.setStart(n, i);
      r.setEnd(n, i + text.length);
      getSelection()!.removeAllRanges();
      getSelection()!.addRange(r);
      return;
    }
    throw new Error(`"${text}" isn't in the field`);
  }, text);
}

/** Puts the caret at the end of a field (End scrolls instead on macOS). */
async function caretAtEnd(field: Locator) {
  await field.click();
  await field.evaluate(el => { getSelection()!.selectAllChildren(el); getSelection()!.collapseToEnd(); });
}

test.describe("formatting", () => {
  const BULLET = "Built a Python service that cut report generation from 40 minutes to 6 minutes.";
  const sent = (api: MockApi) => api.last("PUT", "/api/documents/doc-resume-1")?.body.content;

  test("selected words are made bold, italic, underlined or coloured, and saved as runs", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bar = page.getByRole("toolbar", { name: "Formatting" });
    await expect(bar.getByRole("button", { name: "Bold" })).toBeDisabled(); // nothing focused yet
    const bullet = page.locator("#sheet .r-bullet").first();

    await selectText(bullet, "Python");
    await expect(bar).toContainText("Bullet");
    await bar.getByRole("button", { name: "Bold" }).click();
    await expect(bullet.locator("b")).toHaveText("Python");
    await expect(bar.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-pressed", "true");

    await selectText(bullet, "40 minutes");
    await page.keyboard.press("ControlOrMeta+I");
    await expect(bullet.locator("i")).toHaveText("40 minutes");

    await selectText(bullet, "6 minutes");
    await page.keyboard.press("ControlOrMeta+U");
    await bar.getByRole("button", { name: /Text colour/ }).click();
    await page.getByRole("group", { name: "Text colour" }).getByRole("button", { name: "Navy" }).click();
    await expect(page.getByRole("group", { name: "Text colour" })).toHaveCount(0);
    await expect(bullet).toHaveText(BULLET);

    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    expect(sent(api).experience[0].bullets[0]).toEqual([
      { t: "Built a " }, { t: "Python", b: true }, { t: " service that cut report generation from " }, { t: "40 minutes", i: true },
      { t: " to " }, { t: "6 minutes", u: true, c: "#1f3a5f" }, { t: "." },
    ]);
    expect(sent(api).experience[0].bullets[1]).toBe("Wrote integration tests for the service's REST endpoints.");
    expect(sent(api).format).toBeUndefined();
    // Redrawn from the saved content.
    await expect(bullet.locator("b")).toHaveText("Python");
  });

  test("with nothing selected, a mark applies to the whole field; skill lists stay plain", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bar = page.getByRole("toolbar", { name: "Formatting" });
    await page.locator("#sheet .r-contact span").first().click();
    await expect(bar).toContainText("Contact line");
    await bar.getByRole("button", { name: "Italic" }).click();
    await expect(page.locator("#sheet .r-contact span i").first()).toHaveText("Toronto, ON");

    await page.locator("#sheet .r-skills span").first().click();
    await expect(bar).toContainText("Skills");
    await expect(bar.getByRole("button", { name: "Bold" })).toBeDisabled();
    await expect(bar.getByRole("button", { name: "Bold" })).toHaveAttribute("title", "Lists of skills and awards are plain text");
    await expect(bar.getByRole("button", { name: "Centre" })).toBeEnabled();

    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    expect(sent(api).header.contact[0]).toEqual([{ t: "Toronto, ON", i: true }]);
  });

  test("alignment, size, spacing and blank lines are saved as styles", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bar = page.getByRole("toolbar", { name: "Formatting" });
    const name = page.locator("#sheet .r-name");
    await name.click();
    await expect(bar).toContainText("Name");
    await expect(bar.getByRole("button", { name: "Centre" })).toHaveAttribute("aria-pressed", "true"); // the default
    await expect(bar.getByText("22 pt")).toBeVisible();
    await bar.getByRole("button", { name: "Align left" }).click();
    await expect(name).toHaveCSS("text-align", "left");
    await bar.getByRole("button", { name: "Larger text" }).click();
    await bar.getByRole("button", { name: "Larger text" }).click();
    await expect(bar.getByText("23 pt")).toBeVisible();

    const bullet = page.locator("#sheet .r-bullet").first();
    await bullet.click();
    await bar.getByRole("button", { name: "Add a blank line after" }).click();
    await expect(bullet).not.toHaveCSS("padding-bottom", "0px");
    await bar.getByRole("button", { name: "Space before" }).click();
    await page.locator(".ui-select.open").getByRole("option", { name: "½ line", exact: true }).click();
    await bar.getByRole("button", { name: "Justify" }).click();

    // A row with dates can't be aligned, but its entry can have space around it.
    await page.locator("#sheet .r-entry strong").nth(1).click();
    await expect(bar).toContainText("Employer");
    await expect(bar.getByRole("button", { name: "Centre" })).toBeDisabled();
    await bar.getByRole("button", { name: "Add a blank line after" }).click();

    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    const styles = sent(api).format.styles;
    expect(styles["header.name"].align).toBe("left");
    expect(styles["header.name"].size).toBeCloseTo(23 / 11, 3);
    expect(styles["experience.0.bullets.0"]).toEqual({ align: "justify", before: 0.5, after: 1 });
    expect(styles["experience.0"]).toEqual({ after: 1 });
    expect(sent(api).format.page).toBeUndefined();
  });

  test("an emptied bullet takes its style with it", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bar = page.getByRole("toolbar", { name: "Formatting" });
    const bullets = page.locator("#sheet .r-bullet");
    await bullets.nth(1).click();
    await bar.getByRole("button", { name: "Centre" }).click();
    await bullets.nth(0).click();
    await page.keyboard.press("ControlOrMeta+A");
    await page.keyboard.press("Backspace");
    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    expect(sent(api).experience[0].bullets).toEqual(["Wrote integration tests for the service's REST endpoints."]);
    expect(sent(api).format.styles).toEqual({ "experience.0.bullets.0": { align: "center" } });
  });

  test("Shift+Enter starts a new line inside a field, and section titles can be renamed", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bullet = page.locator("#sheet .r-bullet").first();
    await caretAtEnd(bullet);
    await page.keyboard.press("Shift+Enter");
    await page.keyboard.type("Used by 3 teams.");
    await expect(bullet).toBeFocused();
    await expect(bullet.locator("br")).toHaveCount(1);

    const title = page.locator("#sheet .r-section h2").nth(3);
    await title.click();
    await page.keyboard.press("ControlOrMeta+A");
    await page.keyboard.type("Technical skills");
    await page.keyboard.press("Enter");

    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    expect(sent(api).experience[0].bullets[0]).toBe(`${BULLET}\nUsed by 3 teams.`);
    expect(sent(api).headings).toEqual({ skills: "Technical skills" });
    await expect(title).toHaveText("Technical skills");
  });

  test("Page sets the margins, font, text size and line spacing", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const sheet = page.locator("#sheet");
    await expect(sheet).toHaveCSS("padding-top", "48px");
    await page.getByRole("button", { name: "Page" }).click();
    const panel = page.getByRole("group", { name: "Page settings" });
    await panel.getByRole("button", { name: /Wide/ }).click();
    await expect(sheet).toHaveCSS("padding-left", "96px");
    await panel.getByLabel("Top").fill("0.6");
    await panel.getByLabel("Top").press("Enter");
    await expect(sheet).toHaveCSS("padding-top", "57.6px");
    expect(await page.locator("#doc-page-rule").textContent()).toBe("@page { size: letter; margin: 0.6in 1in 1in 1in; }");

    await panel.getByRole("button", { name: "Font" }).click();
    await page.getByRole("option", { name: "Georgia" }).click();
    await expect(sheet).toHaveCSS("font-family", "Georgia, serif");
    await panel.getByRole("button", { name: "Text size" }).click();
    await page.getByRole("option", { name: "10 pt" }).click();
    await expect(sheet).toHaveCSS("font-size", /^13\.33/);
    await panel.getByRole("button", { name: "Line spacing" }).click();
    await page.getByRole("option", { name: "1.15" }).click();

    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    expect(sent(api).format.page).toEqual({ margins: { top: 0.6, right: 1, bottom: 1, left: 1 }, font: "Georgia", size: 10, lineHeight: 1.15 });

    // Reset page goes back to the defaults; it can be undone.
    await page.getByRole("button", { name: "Page" }).click();
    await panel.getByRole("button", { name: "Reset page" }).click();
    await expect(sheet).toHaveCSS("padding-left", "48px");
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(sheet).toHaveCSS("padding-left", "96px");
  });

  test("a fixed text size that runs past one page says so and marks where page 2 starts", async ({ api, page }) => {
    const doc = api.docs["doc-resume-1"];
    const bullet = "Built and maintained a service with a long description that wraps onto a second printed line on the page.";
    doc.content.experience = Array.from({ length: 8 }, (_, i) => ({ ...doc.content.experience[0], organization: `Company ${i}`, bullets: Array(4).fill(bullet), refs: [] }));
    doc.content.format = { page: { size: 12 } };
    await page.goto("./doc.html?id=doc-resume-1");
    await expect(page.locator("#doc-fit")).toHaveText("Runs onto a second page at 12pt. Pick a smaller size, narrower margins, or Auto.");
    await expect(page.locator("#sheet")).toHaveClass(/overflows/);
  });

  test("undo and redo cover typing and formatting", async ({ page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bar = page.getByRole("toolbar", { name: "Formatting" });
    const name = page.locator("#sheet .r-name");
    await expect(bar.getByRole("button", { name: "Undo" })).toBeDisabled();
    await caretAtEnd(name);
    await page.keyboard.type(" Jr");
    await bar.getByRole("button", { name: "Underline" }).click();
    await expect(name.locator("u")).toHaveText("Sam Rivera Jr");

    await page.keyboard.press("ControlOrMeta+Z");
    await expect(name.locator("u")).toHaveCount(0);
    await expect(name).toHaveText("Sam Rivera Jr");
    await expect(name).toBeFocused();
    await page.keyboard.press("ControlOrMeta+Z");
    await expect(name).toHaveText("Sam Rivera");
    await expect(bar.getByRole("button", { name: "Undo" })).toBeDisabled();

    await page.keyboard.press("ControlOrMeta+Shift+Z");
    await expect(name).toHaveText("Sam Rivera Jr");
    await bar.getByRole("button", { name: "Redo" }).click();
    await expect(name.locator("u")).toHaveText("Sam Rivera Jr");
    await expect(bar.getByRole("button", { name: "Redo" })).toBeDisabled();
  });

  test("Clear formatting and Remove all formatting", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bar = page.getByRole("toolbar", { name: "Formatting" });
    const bullet = page.locator("#sheet .r-bullet").first();
    await selectText(bullet, "Python");
    await bar.getByRole("button", { name: "Bold" }).click();
    await bar.getByRole("button", { name: "Centre" }).click();
    await bar.getByRole("button", { name: "Clear formatting" }).click();
    await expect(bullet.locator("b")).toHaveCount(0);
    await expect(bullet).toHaveCSS("text-align", "start");

    await page.locator("#sheet .r-name").click();
    await bar.getByRole("button", { name: "Bold" }).click(); // the name is bold already, so this unbolds it
    await bar.getByRole("button", { name: "Align right" }).click();
    await page.getByRole("button", { name: "Page" }).click();
    await page.getByRole("group", { name: "Page settings" }).getByRole("button", { name: /Narrow/ }).click();
    await page.getByRole("button", { name: "Remove all formatting" }).click();
    await page.getByRole("button", { name: "Save edits" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Saved");
    expect(sent(api).header.name).toBe("Sam Rivera");
    expect(sent(api).experience[0].bullets[0]).toBe(BULLET);
    expect(sent(api).format).toBeUndefined();
  });

  test("the toolbar works from the keyboard and keeps the selection", async ({ page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    const bar = page.getByRole("toolbar", { name: "Formatting" });
    const bullet = page.locator("#sheet .r-bullet").first();
    await selectText(bullet, "Python");
    await bar.getByRole("button", { name: "Bold" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(bar.getByRole("button", { name: "Italic" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(bullet.locator("i")).toHaveText("Python");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await expect(bar.getByRole("button", { name: "Undo" })).toBeFocused();
  });

  test("a formatted document opens with its formatting", async ({ api, page }) => {
    const c = api.docs["doc-resume-1"].content;
    c.header.name = [{ t: "Sam " }, { t: "Rivera", c: "#7a1f2b" }];
    c.headings = { experience: "Work" };
    c.format = { page: { margins: { top: 0.75, right: 0.75, bottom: 0.75, left: 0.75 } }, styles: { "header.name": { align: "right" }, "experience.0.bullets.1": { after: 1 } } };
    await page.goto("./doc.html?id=doc-resume-1");
    const sheet = page.locator("#sheet");
    await expect(sheet.locator(".r-name")).toHaveText("Sam Rivera");
    await expect(sheet.locator(".r-name span")).toHaveCSS("color", "rgb(122, 31, 43)");
    await expect(sheet.locator(".r-name")).toHaveCSS("text-align", "right");
    await expect(sheet.locator(".r-section h2").nth(1)).toHaveText("Work");
    await expect(sheet).toHaveCSS("padding-top", "72px");
    await expect(sheet.locator(".r-bullet").nth(1)).not.toHaveCSS("padding-bottom", "0px");
    await expect(page).toHaveTitle("Sam Rivera – Resume – Acme Robotics");
  });

  test("Download Word gets the file at the fitted size, saving edits first", async ({ api, page }) => {
    await page.goto("./doc.html?id=doc-resume-1");
    await expect(page.locator("#doc-fit")).toHaveText("Fits on one page");
    let download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download Word" }).click();
    expect((await download).suggestedFilename()).toBe("doc-resume-1.docx");
    await expect(page.locator("#doc-msg")).toHaveText("Downloaded the Word file");
    expect(api.last("GET", "/api/documents/doc-resume-1/docx")?.query).toEqual({ fs: "11", sp: "1" });
    expect(api.last("PUT", "/api/documents/doc-resume-1")).toBeUndefined();

    await page.locator("#sheet .r-name").click();
    await page.keyboard.type("x");
    download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download Word" }).click();
    await download;
    await expect(page.locator("#doc-msg")).toHaveText("Saved your edits and downloaded the Word file");
    expect(sent(api)).toBeTruthy();
    await expect(page.getByRole("button", { name: "Save edits" })).toBeDisabled();

    api.on("GET", "/api/documents/doc-resume-1/docx", { status: 404, json: { detail: "That document doesn't exist." } });
    await page.getByRole("button", { name: "Download Word" }).click();
    await expect(page.locator("#doc-msg")).toHaveText("Couldn't make the Word file: That document doesn't exist.");
    await expect(page.locator("#doc-msg")).toHaveClass(/error/);
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
