import { test, expect, fixture, detail } from "../support/test";

const accounts = fixture("prospeo-accounts.json");

test.describe("resume", () => {
  test("no profile yet: a set-up prompt and no summary", async ({ app, api, page }) => {
    api.profile = fixture("profile-empty.json");
    api.ranking = fixture("ranking-status.json").no_profile;
    await app.open("#profile");
    await expect(page.locator("#profile-dot")).toHaveText("Set up");
    await expect(page.locator("#profile-dot")).toBeVisible();
    await expect(page.locator("#who-name")).toHaveText("Set up your profile");
    await expect(page.locator("#who-avatar")).toHaveText("?");
    await expect(page.locator("#resume-status")).toHaveText("");
    await expect(page.locator("#profile-summary")).toBeHidden();
    await expect(page.locator("#raw-edit")).toBeHidden();
    await expect(page.getByText("Drop your resume here or choose a file")).toBeVisible();
  });

  test("with a profile: a summary of what Claude extracted", async ({ app, page }) => {
    await app.open("#profile");
    await expect(page.locator("#resume-status")).toHaveText("Profile updated 2d ago.");
    await expect(page.locator("#resume-status")).toHaveClass(/ok/);
    const summary = page.locator("#profile-summary");
    await expect(summary.locator(".ps-head")).toHaveText("Sam Riverasam-rivera-resume.pdf");
    await expect(summary.locator(".ps-summary")).toHaveText("Computer engineering student who has built backend services and developer tools.");
    await expect(summary.locator("dd")).toHaveText([
      "BASc, Computer Engineering · University of Northfield · May 2028",
      "Software Developer Intern, Harbourview Labs",
      "Trailmap",
      "PythonGoTypeScriptFastAPIReact",
    ]);
  });

  test("an uploaded resume that wasn't read asks you to upload again", async ({ app, api, page }) => {
    api.profile = { ...fixture("profile-empty.json"), has_resume: true, resume_filename: "resume.pdf", resume_chars: 2000 };
    await app.open("#profile");
    await expect(page.locator("#resume-status")).toHaveText("Your resume was uploaded but not read yet. Upload it again to retry.");
    await expect(page.locator("#profile-dot")).toBeHidden();
  });

  test("uploading sends the file, waits for Claude to read it, then shows the profile", async ({ app, api, page }) => {
    api.profile = fixture("profile-empty.json");
    api.profileAfterExtract = fixture("profile.json");
    await app.open("#profile");
    const release = api.hold("POST", "/api/profile/resume");
    await page.locator("#resume-file").setInputFiles({ name: "resume.txt", mimeType: "text/plain", buffer: Buffer.from("Made-up resume text. ".repeat(20)) });
    await expect(page.locator("#resume-status")).toHaveText("Uploading resume.txt…");
    await expect(page.locator("#resume-status")).toHaveClass(/busy/);
    release();
    await expect(page.locator("#resume-status")).toHaveText("Claude is reading your resume… (about 20–40 seconds)");
    await expect(page.locator("#resume-status")).toHaveText("Profile updated 2d ago.", { timeout: 6000 });
    await expect(page.locator("#profile-summary")).toContainText("Sam Rivera");
    await expect(page.locator("#who-name")).toHaveText("Sam Rivera");
    expect(api.last("POST", "/api/profile/resume")?.body).toEqual({ multipart: true, filename: "resume.txt" });
    expect(api.jobRequests()).toHaveLength(0); // the server starts extraction itself
  });

  test("upload errors and extraction errors show in the status line", async ({ app, api, page }) => {
    api.on("POST", "/api/profile/resume", detail(422, "Found almost no text in that file. If it's a scanned PDF, upload a text-based PDF or paste your resume as a .txt file."));
    await app.open("#profile");
    await page.locator("#resume-file").setInputFiles({ name: "scan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
    await expect(page.locator("#resume-status")).toHaveText(/^Found almost no text in that file\./);
    await expect(page.locator("#resume-status")).toHaveClass(/error/);
    await expect(app.toast()).toBeHidden();

    api.on("POST", "/api/profile/resume", { json: { job_id: "job-x", chars: 3000 } });
    api.jobs.set("job-x", { id: "job-x", kind: "extract_profile", payload: {}, polls: 0 });
    api.jobOutcomes.extract_profile = { status: "error", error: "Claude returned something that isn't valid JSON." };
    await page.locator("#resume-file").setInputFiles({ name: "resume.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
    await expect(page.locator("#resume-status")).toHaveText("Claude returned something that isn't valid JSON.", { timeout: 6000 });
  });

  test("an extraction already running when the page opens is shown and followed", async ({ app, api, page }) => {
    api.profile = { ...fixture("profile-empty.json"), has_resume: true, extract_job: "job-pending" };
    api.profileAfterExtract = fixture("profile.json");
    api.jobs.set("job-pending", { id: "job-pending", kind: "extract_profile", payload: {}, polls: 0 });
    await app.open("#profile");
    await expect(page.locator("#resume-status")).toHaveText("Claude is reading your resume…");
    await expect(page.locator("#resume-status")).toHaveText("Profile updated 2d ago.", { timeout: 6000 });
  });

  test("revisiting the page during an extraction doesn't start a second polling loop", async ({ app, api, page }) => {
    api.profile = { ...fixture("profile-empty.json"), has_resume: true, extract_job: "job-pending" };
    api.jobs.set("job-pending", { id: "job-pending", kind: "extract_profile", payload: {}, polls: 0 });
    api.jobOutcomes.extract_profile = { status: "done", polls: 100, result: { ok: true } };
    await app.open("#profile");
    await app.nav("Tracker").click();
    await app.nav("My profile").click();
    await app.nav("Tracker").click();
    await app.nav("My profile").click();
    await page.waitForTimeout(4500);
    // One loop polls every 2 seconds.
    expect(api.calls("GET", "/api/ai/jobs/job-pending").length).toBeLessThanOrEqual(3);
  });

  test("the profile JSON can be fixed by hand; invalid JSON is caught first", async ({ app, api, page }) => {
    await app.open("#profile");
    await page.getByText("Fix extraction mistakes (edit profile JSON)").click();
    const textarea = page.locator("#profile-json");
    await expect(textarea).toHaveValue(/"name": "Sam Rivera"/);
    await textarea.fill("{ not json");
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(app.toast()).toHaveText("That isn't valid JSON. Check for a missing comma or quote.");
    expect(api.calls("PUT", "/api/profile")).toHaveLength(0);

    const data = { ...fixture("profile.json").data, name: "Sam R. Rivera" };
    await textarea.fill(JSON.stringify(data));
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(app.toast()).toHaveText("Profile saved.");
    expect(api.last("PUT", "/api/profile")?.body).toEqual({ data });
    await expect(page.locator("#who-name")).toHaveText("Sam R. Rivera");
  });
});

test.describe("preferences", () => {
  test("shows saved preferences and saves every field, including LinkedIn Premium", async ({ app, api, page }) => {
    await app.open("#profile");
    const form = page.locator("#prefs-form");
    await expect(form.getByLabel("Roles you want (comma-separated)")).toHaveValue("backend, developer tools");
    await expect(form.getByRole("checkbox", { name: "Software" })).toBeChecked();
    await expect(form.getByRole("checkbox", { name: "Canada" })).toBeChecked();
    await expect(form.locator("#pref-terms .chip")).toHaveText(["Summer 2027", "Winter 2027", "Fall 2026"]);
    await expect(app.dropdown("Degree level")).toHaveText("Bachelor's");
    await expect(form.getByRole("checkbox", { name: /I have LinkedIn Premium/ })).not.toBeChecked();

    await form.getByLabel("Roles you want (comma-separated)").fill("backend,  ML infrastructure , ");
    await form.getByText("AI/ML/Data").click();
    await form.getByText("Remote", { exact: true }).click();
    await form.getByText("Fall 2026").click();
    await app.choose("Degree level", "Master's");
    await form.getByLabel("Graduation").fill(" Dec 2027 ");
    await form.getByLabel("Anything else Claude should know").fill("Prefer smaller teams");
    await form.getByText("I have LinkedIn Premium").click();
    await form.getByRole("button", { name: "Save preferences" }).click();

    await expect(page.locator("#prefs-msg")).toHaveText("Saved.");
    expect(api.last("PUT", "/api/profile")?.body).toEqual({ preferences: {
      target_roles: ["backend", "ML infrastructure"],
      categories: ["Software", "AI/ML/Data"],
      regions: ["US", "CA", "REMOTE"],
      terms: ["Summer 2027", "Fall 2026"],
      degree_level: "Master's",
      graduation: "Dec 2027",
      work_authorization: "Canadian citizen; needs sponsorship for the US",
      school: "University of Northfield",
      notes: "Prefer smaller teams",
      linkedin_premium: true,
    } });
    await expect(page.locator("#prefs-msg")).toHaveText("", { timeout: 5000 });
  });

  test("a rejected save shows the server's message", async ({ app, api, page }) => {
    api.on("PUT", "/api/profile", detail(422, "Unknown preference: colour"));
    await app.open("#profile");
    await page.getByRole("button", { name: "Save preferences" }).click();
    await expect(page.locator("#prefs-msg")).toHaveText("Unknown preference: colour");
    await expect(page.locator("#prefs-msg")).toHaveClass(/error/);
  });
});

test.describe("ranking panel", () => {
  test("shows what's been scored, and needs a resume to run", async ({ app, api, page }) => {
    await app.open("#profile");
    const panel = page.locator(".rank-panel");
    await expect(panel.locator(".rank-status")).toHaveText("9 listings with a keyword score, 2 ranked by Claude 1d ago. Keyword scores updated 1h ago.");
    await expect(panel.getByRole("button", { name: "Rank top 40 with Claude" })).toBeEnabled();
    expect(api.jobRequests()).toHaveLength(0);

    api.profile = fixture("profile-empty.json");
    api.ranking = fixture("ranking-status.json").no_profile;
    await app.reload();
    await expect(panel.locator(".rank-status")).toHaveText("Add your resume above to score listings.");
    await expect(panel.getByRole("button", { name: "Rank top 40 with Claude" })).toBeDisabled();
    await expect(panel.getByRole("button", { name: "Recompute keyword scores" })).toBeDisabled();
  });

  test("Recompute keyword scores reports the count and reloads the board", async ({ app, api, page }) => {
    await app.open("#profile");
    const queries = api.listingQueries().length;
    await page.getByRole("button", { name: "Recompute keyword scores" }).click();
    await expect(page.locator(".rank-panel [data-rank-msg]")).toHaveText("Scored 1,234 listings in 0.41s.");
    await expect.poll(() => api.listingQueries().length).toBeGreaterThan(queries);
    expect(api.jobRequests()).toHaveLength(0);
  });

  test("Rank top 40 with Claude runs only on click, with progress and a result", async ({ app, api, page }) => {
    api.jobOutcomes.rank_listings = { status: "done", polls: 1, result: { ranked: 40, requested: 40, skipped: 0, batches: 2, failed_batches: 0, error: null, seconds: 52.3 } };
    await app.open("#profile");
    const button = page.getByRole("button", { name: "Rank top 40 with Claude" });
    await button.click();
    expect(api.jobRequests("rank_listings")[0].body).toEqual({ kind: "rank_listings", payload: { limit: 40 } });
    await expect(button).toBeDisabled();
    await expect(page.locator(".rank-panel [data-rank-msg]")).toHaveText(/^(Waiting to start…|Claude is ranking listings…) \d+s$/);
    await expect(page.locator(".rank-panel [data-rank-msg]")).toHaveText("Ranked 40 listings in 52s.", { timeout: 8000 });
    await expect(button).toBeEnabled();
  });

  test("partly failed or empty Claude rankings say so", async ({ app, api, page }) => {
    api.jobOutcomes.rank_listings = { status: "done", result: { ranked: 20, requested: 40, skipped: 20, batches: 2, failed_batches: 1, error: "Claude timed out.", seconds: 90 } };
    await app.open("#profile");
    await page.getByRole("button", { name: "Rank top 40 with Claude" }).click();
    const msg = page.locator(".rank-panel [data-rank-msg]");
    await expect(msg).toHaveText("Ranked 20 listings in 90s. 20 couldn't be ranked: Claude timed out.", { timeout: 6000 });
    await expect(msg).toHaveClass(/error/);

    api.jobOutcomes.rank_listings = { status: "done", result: { ranked: 0, requested: 0, skipped: 0, batches: 0, seconds: 0, message: "Every listing in this selection already has a Claude score." } };
    await page.getByRole("button", { name: "Rank top 40 with Claude" }).click();
    await expect(msg).toHaveText("Every listing in this selection already has a Claude score.", { timeout: 6000 });
  });
});

test.describe("integrations", () => {
  const panel = (page: any) => page.locator(".fp-integrations");

  test("a connected key is shown masked with credits and renewal", async ({ app, page }) => {
    await app.open("#profile");
    await expect(panel(page).locator(".fp-int-status")).toHaveText("Key pk_te…7f3a · FREE plan · 57 credits left, renews 2026-11-01");
    await expect(panel(page).getByRole("textbox", { name: "Prospeo API key" })).toHaveAttribute("placeholder", "Paste a new key to replace it");
    await expect(panel(page).getByRole("button", { name: "Replace key" })).toBeVisible();
    await expect(panel(page).getByRole("button", { name: "Remove key" })).toBeVisible();
  });

  test("replacing the key saves it and shows the new masked key", async ({ app, api, page }) => {
    await app.open("#profile");
    const input = panel(page).getByRole("textbox", { name: "Prospeo API key" });
    await expect(input).toHaveAttribute("type", "password");
    await panel(page).getByRole("button", { name: "Replace key" }).click(); // empty: nothing sent
    expect(api.calls("PUT", "/api/integrations/prospeo")).toHaveLength(0);
    await input.fill("  pk_made_up_key_0000abcd ");
    await panel(page).getByRole("button", { name: "Replace key" }).click();
    expect(api.last("PUT", "/api/integrations/prospeo")?.body).toEqual({ key: "pk_made_up_key_0000abcd" });
    await expect(panel(page).locator(".fp-int-status")).toHaveText(/^Key pk_ma…abcd · FREE plan/);
  });

  test("a key that can't be valid is caught before sending", async ({ app, api, page }) => {
    await app.open("#profile");
    await panel(page).getByRole("textbox", { name: "Prospeo API key" }).fill("short");
    await panel(page).getByRole("button", { name: "Replace key" }).click();
    await expect(panel(page).locator(".fp-int-msg")).toHaveText("That doesn't look like a Prospeo API key. Copy it from the API page on prospeo.io.");
    expect(api.calls("PUT", "/api/integrations/prospeo")).toHaveLength(0);
  });

  test("a rejected key shows Prospeo's message", async ({ app, api, page }) => {
    api.on("PUT", "/api/integrations/prospeo", detail(422, "Prospeo returned HTTP 401."));
    await app.open("#profile");
    await panel(page).getByRole("textbox", { name: "Prospeo API key" }).fill("pk_wrong_key_123456");
    await panel(page).getByRole("button", { name: "Replace key" }).click();
    await expect(panel(page).locator(".fp-int-msg")).toHaveText("Prospeo returned HTTP 401.");
    await expect(panel(page).locator(".fp-int-msg")).toHaveClass(/error/);
  });

  test("removing the key shows the not-connected state", async ({ app, api, page }) => {
    await app.open("#profile");
    await panel(page).getByRole("button", { name: "Remove key" }).click();
    await expect(panel(page).locator(".fp-int-status")).toHaveText(/^Not connected\. Create a free account at prospeo\.io/);
    await expect(panel(page).getByRole("button", { name: "Save key" })).toBeVisible();
    await expect(panel(page).getByRole("button", { name: "Remove key" })).toHaveCount(0);
    expect(api.calls("DELETE", "/api/integrations/prospeo")).toHaveLength(1);
  });

  test("not connected, and a key Prospeo rejects, are explained", async ({ app, api, page }) => {
    api.account = accounts.not_configured;
    await app.open("#profile");
    await expect(panel(page).getByRole("textbox", { name: "Prospeo API key" })).toHaveAttribute("placeholder", "Prospeo API key");
    await expect(panel(page).getByRole("button", { name: "Save key" })).toBeVisible();

    api.account = accounts.error;
    await app.reload();
    await expect(panel(page).locator(".fp-int-status .form-msg.error")).toHaveText("Prospeo returned HTTP 401.");
  });

  test("Delete saved contacts asks first, then deletes them all and reports how many", async ({ app, api, page }) => {
    await app.open("#profile");
    let message = "";
    page.once("dialog", d => { message = d.message(); d.dismiss(); });
    await panel(page).getByRole("button", { name: "Delete saved contacts" }).click();
    expect(message).toBe("Delete every saved contact and search? This can't be undone.");
    expect(api.calls("DELETE", "/api/people/contacts")).toHaveLength(0);
    page.once("dialog", d => d.accept());
    await panel(page).getByRole("button", { name: "Delete saved contacts" }).click();
    await expect(panel(page).locator(".fp-int-msg")).toHaveText("Deleted 6 saved contacts.");
    expect(api.calls("DELETE", "/api/people/contacts")).toHaveLength(1);
  });
});
