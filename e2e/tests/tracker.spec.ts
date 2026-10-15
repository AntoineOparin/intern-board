import { test, expect, NOW, HOUR } from "../support/test";

test.describe("kanban", () => {
  test("five columns with counts, cards in position order, and deadline, closed and region tags", async ({ app, page }) => {
    await app.open("#tracker");
    await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();
    await expect(page.locator("#kanban .column h2")).toHaveText(["saved2", "applied1", "interviewing1", "offer0", "rejected1"]);
    await expect(app.column("saved").locator(".card .c-company")).toHaveText(["Acme Robotics", "Maple Systems"]);
    await expect(app.column("offer")).toContainText("Drop cards here");

    await expect(app.card("Acme Robotics").locator(".tag")).toHaveText(["Due Oct 16", "Canada"]);
    await expect(app.card("Acme Robotics").locator(".tag").first()).toHaveClass(/warn/);
    await expect(app.card("Orbit Analytics").locator(".tag")).toHaveText(["Due today", "US", "Remote"]);
    await expect(app.card("Juniper Shield").locator(".tag").first()).toHaveText("Overdue · Oct 10");
    await expect(app.card("Juniper Shield").locator(".tag").first()).toHaveClass(/danger/);
    await expect(app.card("Kestrel Games").locator(".tag")).toHaveText(["Due Oct 30", "Posting closed", "Canada"]);
    await expect(app.card("Maple Systems").locator(".c-notes")).toHaveText("Referral from a classmate");
    await expect(app.card("Acme Robotics")).toHaveAttribute("aria-label", "Acme Robotics: Software Engineer Intern - Summer 2027");
  });

  test("dragging a card to an empty column saves the new stage at position 0", async ({ app, api, page }) => {
    await app.open("#tracker");
    await app.card("Acme Robotics").dragTo(app.column("offer"));
    await expect(app.column("offer").locator(".card")).toHaveCount(1);
    await expect.poll(() => api.last("PUT", "/api/tracker/simplify:acme-swe-27")?.body).toEqual({ status: "offer", position: 0 });
    await expect(page.locator("#kanban .column h2")).toHaveText(["saved1", "applied1", "interviewing1", "offer1", "rejected1"]);
  });

  test("dropping above or below a card positions between its neighbours", async ({ app, api }) => {
    await app.open("#tracker");
    // Orbit is the only applied card (position 1). Above it -> 0; below it -> 2.
    await app.card("Maple Systems").dragTo(app.card("Orbit Analytics"), { targetPosition: { x: 20, y: 4 } });
    await expect.poll(() => api.last("PUT", "/api/tracker/negarprh:maple-firmware")?.body).toEqual({ status: "applied", position: 0 });
    await expect(app.column("applied").locator(".c-company")).toHaveText(["Maple Systems", "Orbit Analytics"]);

    const orbit = app.card("Orbit Analytics");
    const box = (await orbit.boundingBox())!;
    await app.card("Acme Robotics").dragTo(orbit, { targetPosition: { x: 20, y: box.height - 4 } });
    await expect.poll(() => api.last("PUT", "/api/tracker/simplify:acme-swe-27")?.body).toEqual({ status: "applied", position: 2 });
    await expect(app.column("applied").locator(".c-company")).toHaveText(["Maple Systems", "Orbit Analytics", "Acme Robotics"]);

    // Between two cards: the average of their positions.
    await app.card("Juniper Shield").dragTo(app.card("Orbit Analytics"), { targetPosition: { x: 20, y: 4 } });
    await expect.poll(() => api.last("PUT", "/api/tracker/simplify:juniper-sec")?.body).toEqual({ status: "applied", position: 0.5 });
  });

  test("a failed move puts the card back", async ({ app, api }) => {
    api.on("PUT", /^\/api\/tracker\//, { status: 500, json: { detail: "Database is locked" } });
    await app.open("#tracker");
    await app.card("Acme Robotics").dragTo(app.column("offer"));
    await expect(app.toast()).toHaveText("Request failed: Database is locked");
    await expect(app.column("saved").locator(".c-company")).toHaveText(["Acme Robotics", "Maple Systems"]);
    await expect(app.column("offer").locator(".card")).toHaveCount(0);
  });

  test("cards move with Alt and the arrow keys (new frontend)", async ({ app, api, page }) => {
    test.skip(process.env.FRONTEND !== "new", "The old tracker has no keyboard moves; the plan adds them in step 4.");
    await app.open("#tracker");
    await app.card("Acme Robotics").focus();
    await page.keyboard.press("Alt+ArrowRight");
    await expect.poll(() => api.last("PUT", "/api/tracker/simplify:acme-swe-27")?.body).toEqual({ status: "applied", position: 2 });
    await expect(app.column("applied").locator(".c-company")).toHaveText(["Orbit Analytics", "Acme Robotics"]);
    await expect(app.card("Acme Robotics")).toBeFocused();
    await expect(page.getByRole("status").filter({ hasText: "Moved to applied." })).toHaveCount(1);

    await page.keyboard.press("Alt+ArrowUp");
    await expect.poll(() => api.last("PUT", "/api/tracker/simplify:acme-swe-27")?.body).toEqual({ status: "applied", position: 0 });
    await expect(app.column("applied").locator(".c-company")).toHaveText(["Acme Robotics", "Orbit Analytics"]);

    await page.keyboard.press("Alt+ArrowLeft");
    await page.keyboard.press("Alt+ArrowLeft"); // already in the first stage: stays
    await expect(app.column("saved").locator(".c-company")).toHaveText(["Maple Systems", "Acme Robotics"]);
    expect(api.calls("PUT", "/api/tracker/simplify:acme-swe-27")).toHaveLength(3);
  });

  test("the empty tracker shows a prompt to browse listings", async ({ app, api, page }) => {
    api.tracker.items = [];
    await app.open("#tracker");
    await expect(page.getByText("Nothing tracked yet")).toBeVisible();
    await expect(page.locator("#kanban .column")).toHaveCount(5);
    await expect(page.locator("#tracker-count")).toHaveText("");
    await page.locator("#tracker-empty").getByRole("link", { name: "Browse listings" }).click();
    await expect(app.section("board")).toBeVisible();
  });
});

test.describe("side panel", () => {
  test("opens on click or Enter with the listing's details", async ({ app, page }) => {
    await app.open("#tracker");
    await app.card("Kestrel Games").click();
    const drawer = app.drawer();
    await expect(drawer).toBeVisible();
    await expect(drawer.locator("#drawer-company")).toHaveText("Kestrel Games");
    await expect(drawer.locator("#drawer-title")).toHaveText("QA Automation Intern");
    await expect(drawer.locator("#drawer-sub")).toHaveText("Montreal, QC · posting closed");
    await expect(drawer.getByRole("radio", { name: "rejected" })).toBeChecked();
    await expect(drawer.getByLabel("Deadline")).toHaveValue("2026-10-30");
    await expect(drawer.getByRole("link", { name: "Open posting ↗" })).toHaveAttribute("href", "https://jobs.example.com/kestrel/qa");
    await expect(drawer.getByRole("heading", { name: "Documents" })).toBeVisible();
    await expect(drawer.getByRole("heading", { name: "People" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();

    await app.card("Maple Systems").focus();
    await page.keyboard.press("Enter");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByLabel("Notes")).toHaveValue("Referral from a classmate");
    await drawer.getByRole("button", { name: "Close" }).click();
    await expect(drawer).toBeHidden();
  });

  test("Save sends stage, deadline and notes, and the card updates", async ({ app, api, page }) => {
    await app.open("#tracker");
    await app.card("Maple Systems").click();
    const drawer = app.drawer();
    await drawer.locator("label[data-stage=interviewing]").click();
    await drawer.getByLabel("Deadline").fill("2026-10-21");
    await drawer.getByLabel("Notes").fill("Phone screen booked");
    await drawer.getByRole("button", { name: "Save" }).click();
    await expect(drawer).toBeHidden();
    await expect.poll(() => api.last("PUT", "/api/tracker/negarprh:maple-firmware")?.body)
      .toEqual({ status: "interviewing", deadline: "2026-10-21", notes: "Phone screen booked" });
    await expect(app.column("interviewing").locator(".c-company")).toContainText(["Maple Systems"]);
    await expect(app.card("Maple Systems").locator(".c-notes")).toHaveText("Phone screen booked");
    await expect(app.card("Maple Systems").locator(".tag").first()).toHaveText("Due Oct 21");
  });

  test("a failed save keeps the panel open with your edits", async ({ app, api }) => {
    api.on("PUT", /^\/api\/tracker\//, { status: 500, json: { detail: "Database is locked" } });
    await app.open("#tracker");
    await app.card("Maple Systems").click();
    await app.drawer().getByLabel("Notes").fill("Phone screen booked");
    await app.drawer().getByRole("button", { name: "Save" }).click();
    await expect(app.toast()).toHaveText("Request failed: Database is locked");
    await expect(app.drawer()).toBeVisible();
    await expect(app.drawer().getByLabel("Notes")).toHaveValue("Phone screen booked");
  });

  test("deadlines count calendar days, also in the morning", async ({ app, api, page }) => {
    await page.clock.setFixedTime((NOW - 4 * HOUR) * 1000); // 10:00
    api.tracked("simplify:acme-swe-27").deadline = "2026-10-13"; // yesterday
    api.tracked("simplify:orbit-ml").deadline = "2026-10-14"; // today
    api.tracked("negarprh:maple-firmware").deadline = "2026-10-15"; // tomorrow
    await app.open("#tracker");
    await expect(app.card("Acme Robotics").locator(".tag").first()).toHaveText("Overdue · Oct 13");
    await expect(app.card("Orbit Analytics").locator(".tag").first()).toHaveText("Due today");
    await expect(app.card("Maple Systems").locator(".tag").first()).toHaveText("Due Oct 15");
    await expect(page.locator("[data-stat=due] .stat-value")).toHaveText("2");
  });

  test("clearing the deadline sends an empty string", async ({ app, api }) => {
    await app.open("#tracker");
    await app.card("Acme Robotics").click();
    await app.drawer().getByLabel("Deadline").fill("");
    await app.drawer().getByRole("button", { name: "Save" }).click();
    await expect.poll(() => api.last("PUT", "/api/tracker/simplify:acme-swe-27")?.body)
      .toEqual({ status: "saved", deadline: "", notes: "" });
    await expect(app.card("Acme Robotics").locator(".tag")).toHaveText(["Canada"]);
  });

  test("closing without saving sends nothing", async ({ app, api, page }) => {
    await app.open("#tracker");
    await app.card("Acme Robotics").click();
    await app.drawer().getByLabel("Notes").fill("Not saved");
    await page.mouse.click(5, 5); // the backdrop
    await expect(app.drawer()).toBeHidden();
    expect(api.calls("PUT", /^\/api\/tracker\//)).toHaveLength(0);
  });

  test("Remove deletes the card and the board shows Track again", async ({ app, api, page }) => {
    await app.open("#board");
    await app.listing("Acme Robotics").getByRole("button", { name: "saved" }).click();
    await app.drawer().getByRole("button", { name: "Remove" }).click();
    await expect(app.drawer()).toBeHidden();
    await expect.poll(() => api.calls("DELETE", "/api/tracker/simplify:acme-swe-27").length).toBe(1);
    await expect(app.listing("Acme Robotics").getByRole("button", { name: "Track" })).toBeVisible();
    await expect(page.locator("#tracker-count")).toHaveText("4");
    await app.nav("Tracker").click();
    await expect(app.card("Acme Robotics")).toHaveCount(0);
  });

  test("the People section links to Find People for that listing", async ({ app, page }) => {
    await app.open("#tracker");
    await app.card("Acme Robotics").click();
    await app.drawer().getByRole("link", { name: "Find people at Acme Robotics" }).click();
    await expect(app.drawer()).toBeHidden();
    await expect(page).toHaveURL(/#people\?listing=simplify%3Aacme-swe-27$/);
    await expect(page.getByRole("heading", { name: "Who are you looking for at Acme Robotics?" })).toBeVisible();
  });

  test("deadlines this week count only open stages due in the next 7 days", async ({ app, api, page }) => {
    api.tracker.items.find((i: any) => i.id === "simplify:kestrel-qa").deadline = "2026-10-15"; // rejected: not counted
    await app.open();
    await expect(page.locator("[data-stat=due] .stat-value")).toHaveText("2");
  });
});
