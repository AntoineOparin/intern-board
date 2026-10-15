// Resume tailor and Cover letter pages, and the Documents section they share with the tracker side panel.
import { test, expect } from "../support/test";

const ACME = "simplify:acme-swe-27";
const MAPLE = "negarprh:maple-firmware";
const body = (page: any) => page.locator("#tool-body");

test.describe("tool pages", () => {
  test("Resume tailor lists tracked internships by stage and shows the Documents section", async ({ app, api, page }) => {
    await app.open("#resume");
    await expect(page.getByRole("heading", { name: "Resume tailor", level: 1 })).toBeVisible();
    await expect(page.locator("#tool-lede")).toHaveText("A one-page resume rewritten for one internship, using only what's in your profile. Edit it, then save as PDF.");
    await expect(page.locator("#tool-hint")).toHaveText("Showing internships from your tracker.");
    await expect(page.locator("#tool-listing option")).toHaveText([
      "Acme Robotics — Software Engineer Intern - Summer 2027 (saved)",
      "Maple Systems — Firmware Intern (saved)",
      "Orbit Analytics — Machine Learning Intern (applied)",
      "Juniper Shield — Security Engineering Intern (interviewing)",
      "Kestrel Games — QA Automation Intern (rejected)",
    ]);
    await expect(app.dropdown("Internship")).toHaveText("Acme Robotics — Software Engineer Intern - Summer 2027 (saved)");
    await expect(body(page).getByRole("heading", { name: "Documents" })).toBeVisible();
    await expect(body(page).locator(".docs-desc-status")).toHaveText("Job description from the company's job board · 4,210 characters");
    await expect(body(page).getByRole("button", { name: "Load description" })).toBeHidden();
    expect(api.last("GET", "/api/documents")?.query).toEqual({ listing_id: ACME });
    expect(api.jobRequests()).toHaveLength(0);
  });

  test("the documents list shows kind, age, edits, and older-profile and no-description tags", async ({ app, page }) => {
    await app.open("#resume");
    const items = body(page).locator(".docs-item");
    await expect(items).toHaveCount(2);
    await expect(items.nth(0).locator(".docs-item-main")).toHaveText(/Resume\s+2d ago · edited/);
    await expect(items.nth(0).locator(".tag")).toHaveCount(0);
    await expect(items.nth(0).getByRole("link", { name: "Open ↗" })).toHaveAttribute("href", "/doc.html?id=doc-resume-1");
    await expect(items.nth(0).getByRole("link", { name: "Open ↗" })).toHaveAttribute("target", "_blank");
    await expect(items.nth(1).locator(".docs-item-main")).toHaveText(/Cover letter\s+5d ago/);
    await expect(items.nth(1).locator(".tag")).toHaveText(["Older profile", "No description"]);
    await expect(items.nth(1).locator(".tag").first()).toHaveAttribute("title", "Your profile changed after this was written");
  });

  test("picking another internship is remembered (toolListing) across reloads and pages", async ({ app, api, page }) => {
    await app.open("#resume");
    await app.choose("Internship", "Maple Systems — Firmware Intern (saved)");
    await expect(body(page).locator(".docs-desc-status")).toHaveText("Job description not loaded yet. Writing a document loads it first.");
    await expect(body(page).getByRole("button", { name: "Load description" })).toBeVisible();
    await expect(body(page).locator(".docs-empty")).toHaveText("No documents for this listing yet.");
    expect(await page.evaluate(() => localStorage.getItem("toolListing"))).toBe(JSON.stringify(MAPLE));

    await app.reload();
    await expect(app.dropdown("Internship")).toHaveText("Maple Systems — Firmware Intern (saved)");
    await app.nav("Cover letter").click();
    await expect(page.getByRole("heading", { name: "Cover letter", level: 1 })).toBeVisible();
    await expect(page.locator("#tool-lede")).toHaveText("A short cover letter for one internship, in the tone you pick. It draws on real experience from your profile.");
    await expect(app.dropdown("Internship")).toHaveText("Maple Systems — Firmware Intern (saved)");
    expect(api.jobRequests()).toHaveLength(0);
  });

  test("with nothing tracked, the tool pages ask you to track an internship first", async ({ app, api, page }) => {
    api.tracker.items = [];
    await app.open("#cover");
    await expect(page.getByText("Track an internship first")).toBeVisible();
    await expect(page.locator(".tool-picker")).toBeHidden();
    await expect(page.locator("#tool-body")).toBeHidden();
  });
});

test.describe("writing documents", () => {
  test("Tailor resume runs only on click, shows progress, then lists the document and its notes", async ({ app, api, page }) => {
    api.jobOutcomes.tailor_resume = { status: "done", polls: 1, result: { document_id: "doc-resume-new" } };
    await app.open("#resume");
    await body(page).getByRole("button", { name: "Tailor resume" }).click();
    expect(api.jobRequests("tailor_resume")[0].body).toEqual({ kind: "tailor_resume", payload: { listing_id: ACME } });
    await expect(body(page).locator(".docs-msg")).toHaveText(/^Tailoring resume… \d+s$/);
    await expect(body(page).locator(".docs-msg")).toHaveClass(/busy/);
    for (const name of ["Tailor resume", "Write cover letter"]) await expect(body(page).getByRole("button", { name })).toBeDisabled();

    await expect(body(page).locator(".docs-item")).toHaveCount(3, { timeout: 8000 });
    await expect(body(page).locator(".docs-msg")).toHaveClass(/ok/);
    const notes = body(page).locator(".docs-notes");
    await expect(notes.locator(".docs-notes-title")).toHaveText(["Emphasised", "Gaps in the posting"]);
    await expect(notes).toContainText("The posting asks for ROS experience, which your profile doesn't show.");
    expect(api.last("GET", "/api/documents/doc-resume-new")).toBeTruthy();
    await expect(body(page).getByRole("button", { name: "Tailor resume" })).toBeEnabled();
  });

  // Known bug: writeDoc() looks up KIND_LABEL by the job kind ("tailor_resume"), whose labels are
  // keyed "resume", so the page says "undefined ready. …". Enable once fixed.
  test.fixme("Tailor resume finishes with 'Resume ready'", async ({ app, page }) => {
    await app.open("#resume");
    await body(page).getByRole("button", { name: "Tailor resume" }).click();
    await expect(body(page).locator(".docs-msg")).toHaveText("Resume ready. Open it to review, edit and download.", { timeout: 6000 });
  });

  test("Write cover letter runs on click and shows the letter's notes", async ({ app, api, page }) => {
    await app.open("#cover");
    await expect(app.dropdown("Cover letter tone")).toHaveText("Formal");
    await body(page).getByRole("button", { name: "Write cover letter" }).click();
    expect(api.jobRequests("cover_letter")[0].body.payload.listing_id).toBe(ACME);
    await expect(body(page).locator(".docs-msg")).toHaveText("Cover letter ready. Open it to review, edit and download.", { timeout: 6000 });
    await expect(body(page).locator(".docs-notes")).toContainText("Written without the job description. Paste it above and write again for a closer fit.");
    await expect(body(page).locator(".docs-notes .docs-notes-title")).toHaveText(["Check before sending", "Draws on"]);
  });

  // Known bug: select.js copies the select's classes onto its wrapper, so documents.js's
  // querySelector(".docs-tone") finds the wrapper <span> and the tone is never sent (the server
  // then writes a formal letter). Enable once fixed.
  test.fixme("Write cover letter sends the tone picked in the dropdown", async ({ app, api, page }) => {
    await app.open("#cover");
    await app.choose("Cover letter tone", "Conversational");
    await body(page).getByRole("button", { name: "Write cover letter" }).click();
    expect(api.jobRequests("cover_letter")[0].body).toEqual({ kind: "cover_letter", payload: { listing_id: ACME, tone: "conversational" } });
  });

  test("a failed job shows its error and re-enables the buttons", async ({ app, api, page }) => {
    api.jobOutcomes.tailor_resume = { status: "error", error: "Add your resume on the Profile tab first." };
    await app.open("#resume");
    await body(page).getByRole("button", { name: "Tailor resume" }).click();
    await expect(body(page).locator(".docs-msg")).toHaveText("Add your resume on the Profile tab first.", { timeout: 6000 });
    await expect(body(page).locator(".docs-msg")).toHaveClass(/error/);
    await expect(body(page).getByRole("button", { name: "Tailor resume" })).toBeEnabled();
  });

  test("a job keeps running when the side panel closes, and reopening shows its progress", async ({ app, api, page }) => {
    api.jobOutcomes.tailor_resume = { status: "done", polls: 2, result: { document_id: "doc-resume-new" } };
    await app.open("#tracker");
    await app.card("Acme Robotics").click();
    await app.drawer().getByRole("button", { name: "Tailor resume" }).click();
    await page.keyboard.press("Escape");
    await app.card("Acme Robotics").click();
    await expect(app.drawer().locator(".docs-msg")).toHaveText(/^Tailoring resume… \d+s$/);
    await expect(app.drawer().getByRole("button", { name: "Tailor resume" })).toBeDisabled();
    await expect(app.drawer().locator(".docs-item")).toHaveCount(3, { timeout: 8000 });
    await expect(app.drawer().locator(".docs-msg")).toHaveClass(/ok/);
    expect(api.jobRequests("tailor_resume")).toHaveLength(1);
  });

  test("Delete asks first, then removes the document", async ({ app, api, page }) => {
    await app.open("#resume");
    const first = body(page).locator(".docs-item").first();
    let message = "";
    page.once("dialog", d => { message = d.message(); d.dismiss(); });
    await first.getByRole("button", { name: "Delete" }).click();
    expect(message).toBe("Delete this resume? This can't be undone.");
    expect(api.calls("DELETE", /^\/api\/documents\//)).toHaveLength(0);

    page.once("dialog", d => d.accept());
    await first.getByRole("button", { name: "Delete" }).click();
    await expect(body(page).locator(".docs-item")).toHaveCount(1);
    expect(api.calls("DELETE", "/api/documents/doc-resume-1")).toHaveLength(1);
  });
});

test.describe("job description", () => {
  test("Load description fetches it with Claude on click", async ({ app, api, page }) => {
    await app.storage({ toolListing: MAPLE });
    await app.open("#resume");
    await body(page).getByRole("button", { name: "Load description" }).click();
    expect(api.jobRequests("fetch_description")[0].body).toEqual({ kind: "fetch_description", payload: { listing_id: MAPLE } });
    await expect(body(page).locator(".docs-msg")).toHaveText("Job description loaded.", { timeout: 6000 });
    await expect(body(page).locator(".docs-desc-status")).toHaveText("Job description read from the posting page · 440 characters");
  });

  test("when it can't be loaded, the paste box opens", async ({ app, api, page }) => {
    api.jobOutcomes.fetch_description = { status: "done", result: { text: null, source: null, fetched_at: null } };
    await app.storage({ toolListing: MAPLE });
    await app.open("#resume");
    await body(page).getByRole("button", { name: "Load description" }).click();
    await expect(body(page).locator(".docs-msg")).toHaveText("Couldn't load the job description. Paste it below instead.", { timeout: 6000 });
    await expect(body(page).locator("details.docs-paste")).toHaveAttribute("open", "");
  });

  test("pasting a description needs 50 characters, then saves it", async ({ app, api, page }) => {
    await app.storage({ toolListing: MAPLE });
    await app.open("#resume");
    await body(page).getByText("Paste job description").click();
    const textarea = body(page).getByLabel(/Job description/);
    await textarea.fill("Too short.");
    await body(page).getByRole("button", { name: "Save description" }).click();
    await expect(body(page).locator(".docs-msg")).toHaveText("Paste the full job description (at least 50 characters).");
    expect(api.calls("PUT", /\/description$/)).toHaveLength(0);

    const text = "Firmware interns write C for our sensor boards and test it on real hardware with the team.";
    await textarea.fill(`  ${text}  `);
    await body(page).getByRole("button", { name: "Save description" }).click();
    await expect(body(page).locator(".docs-msg")).toHaveText("Job description saved. New documents will use it.");
    expect(api.last("PUT", `/api/listings/${MAPLE}/description`)?.body).toEqual({ text });
    await expect(body(page).locator("details.docs-paste")).not.toHaveAttribute("open", "");
    await expect(body(page).locator(".docs-desc-status")).toHaveText(`Job description pasted by you · ${text.length} characters`);
  });
});
