// The custom dropdowns (select.js) layered over native <select>s, tested on the board's Category filter.
import { test, expect, NOW } from "../support/test";

test.describe("custom dropdowns", () => {
  test("mouse: opens a listbox, picks an option, updates the label and highlights an active filter", async ({ app, api, page }) => {
    await app.open();
    const button = app.dropdown("Category");
    await expect(button).toHaveText("All categories");
    await expect(button).toHaveAttribute("aria-haspopup", "listbox");
    await expect(button).toHaveAttribute("aria-expanded", "false");

    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "true");
    const list = page.getByRole("listbox");
    await expect(list).toBeVisible();
    await expect(list.getByRole("option")).toHaveText(["All categories", "Software · 5", "AI/ML/Data · 3", "Hardware · 1", "Product · 1", "Quant · 1"]);
    await expect(list.getByRole("option", { name: "All categories" })).toHaveAttribute("aria-selected", "true");

    await list.getByRole("option", { name: "Hardware · 1" }).click();
    await expect(list).toBeHidden();
    await expect(button).toHaveText("Hardware · 1");
    await expect(button).toBeFocused();
    await expect(page.locator(".ui-select", { has: button })).toHaveClass(/\bset\b/);
    await expect.poll(() => api.listingQueries().at(-1)?.category).toBe("Hardware");

    // The sort dropdown never counts as an active filter.
    await app.choose("Sort", "Company A–Z");
    await expect(page.locator(".ui-select", { has: app.dropdown("Sort") })).not.toHaveClass(/\bset\b/);
  });

  test("clicking outside closes without changing the value", async ({ app, api, page }) => {
    await app.open();
    await app.dropdown("Category").click();
    await expect(page.getByRole("listbox")).toBeVisible();
    const queries = api.listingQueries().length;
    await page.locator("#board-heading").click();
    await expect(page.getByRole("listbox")).toBeHidden();
    await expect(app.dropdown("Category")).toHaveText("All categories");
    expect(api.listingQueries().length).toBe(queries);
  });

  test("keyboard: arrows, Home, End, Enter and Escape", async ({ app, api, page }) => {
    await app.open();
    const button = app.dropdown("Category");
    await button.focus();
    await page.keyboard.press("ArrowDown"); // opens
    await expect(button).toHaveAttribute("aria-expanded", "true");
    const active = page.locator(".ui-select-list li.active");
    await expect(active).toHaveText("All categories");

    await page.keyboard.press("ArrowDown");
    await expect(active).toHaveText("Software · 5");
    await expect(button).toHaveAttribute("aria-activedescendant", await active.getAttribute("id") as string);
    await page.keyboard.press("End");
    await expect(active).toHaveText("Quant · 1");
    await page.keyboard.press("ArrowDown"); // stays on the last option
    await expect(active).toHaveText("Quant · 1");
    await page.keyboard.press("Home");
    await expect(active).toHaveText("All categories");
    await page.keyboard.press("ArrowUp"); // stays on the first option
    await expect(active).toHaveText("All categories");

    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Escape");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(button).toHaveText("All categories");

    await page.keyboard.press("Enter"); // opens
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(button).toHaveText("AI/ML/Data · 3");
    await expect.poll(() => api.listingQueries().at(-1)?.category).toBe("AI/ML/Data");

    await page.keyboard.press(" "); // Space opens too
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Tab"); // Tab closes
    await expect(page.getByRole("listbox")).toBeHidden();
  });

  test("type-ahead jumps to an option, choosing it straight away when closed", async ({ app, api, page }) => {
    await app.open();
    const button = app.dropdown("Category");
    await button.focus();
    await page.keyboard.press("q");
    await expect(button).toHaveText("Quant · 1");
    await expect.poll(() => api.listingQueries().at(-1)?.category).toBe("Quant");

    await page.keyboard.press("ArrowDown");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await page.clock.setFixedTime((NOW + 1) * 1000); // a second later, so "h" starts a new search
    await page.keyboard.press("h");
    await expect(page.locator(".ui-select-list li.active")).toHaveText("Hardware · 1");
    await expect(button).toHaveText("Quant · 1"); // only moves the highlight while open
    await page.keyboard.press("a"); // within 700ms: "ha" still matches Hardware
    await expect(page.locator(".ui-select-list li.active")).toHaveText("Hardware · 1");
    await page.keyboard.press("Enter");
    await expect(button).toHaveText("Hardware · 1");
  });

  test("labels follow programmatic changes: Clear filters, stat buttons and filters restored later", async ({ app, page }) => {
    await app.open();
    await app.choose("Category", "Software · 5");
    await page.getByRole("button", { name: /Direct from companies/ }).click();
    await expect(app.dropdown("Source")).toHaveText("Company boards");
    await expect(page.locator(".ui-select", { has: app.dropdown("Source") })).toHaveClass(/\bset\b/);

    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(app.dropdown("Category")).toHaveText("All categories");
    await expect(app.dropdown("Source")).toHaveText("All sources");
    await expect(page.locator(".ui-select", { has: app.dropdown("Category") })).not.toHaveClass(/\bset\b/);
  });

  test("opens downwards with room below, and upwards near the bottom of the screen", async ({ app, page }) => {
    await app.open();
    const button = app.dropdown("Sort");
    await button.click();
    await expect(page.locator(".ui-select.open")).not.toHaveClass(/\bup\b/);
    await page.keyboard.press("Escape");
    // Opening scrolls the highlighted option into view, which can scroll the page; start from the top.
    await page.evaluate(() => scrollTo(0, 0));

    const box = (await button.boundingBox())!;
    const height = Math.ceil(box.y + box.height + 60);
    await page.setViewportSize({ width: 1440, height });
    // Resizing closes open dropdowns; let the resize event fire before opening one.
    await page.waitForFunction(h => innerHeight === h, height);
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    await button.click();
    await expect(page.locator(".ui-select.open")).toHaveClass(/\bup\b/);
    const list = (await page.getByRole("listbox").boundingBox())!;
    expect(list.y + list.height).toBeLessThanOrEqual(box.y + 1);
  });

  test("dropdowns inside the side panel close on Escape without closing the panel", async ({ app, page }) => {
    await app.open("#tracker");
    await app.card("Acme Robotics").click();
    const tone = app.drawer().getByRole("button", { name: "Cover letter tone" });
    await tone.click();
    await expect(tone).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(tone).toHaveAttribute("aria-expanded", "false");
    await expect(app.drawer()).toBeVisible();
  });
});
