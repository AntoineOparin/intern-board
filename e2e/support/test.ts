import { test as base, expect, type Page } from "@playwright/test";
import { MockApi } from "./mock-api";
import { NOW_MS } from "./clock";

export { expect };
export { NOW, HOUR, DAY } from "./clock";
export { fixture, detail, validationError } from "./mock-api";

type Fixtures = { api: MockApi; app: App };

export const test = base.extend<Fixtures>({
  // auto: every test gets the mock, even one that never mentions `api`, so nothing reaches a real server.
  api: [async ({ page, baseURL }, use) => {
    const api = new MockApi(baseURL!);
    const pageErrors: string[] = [];
    page.on("pageerror", err => { if (!api.allowedPageErrors.some(re => re.test(err.message))) pageErrors.push(err.message); });
    await api.install(page);
    await page.clock.setFixedTime(NOW_MS);
    await use(api);
    expect(api.unexpected, "requests that weren't mocked").toEqual([]);
    expect(pageErrors, "uncaught errors in the page").toEqual([]);
  }, { auto: true }],
  app: async ({ page, api }, use) => {
    await use(new App(page, api));
  },
});

export class App {
  constructor(readonly page: Page, readonly api: MockApi) {}

  /** Seed localStorage before the app's scripts run. Only applies to the first load in a tab,
   *  so reloads see whatever the app stored. */
  async storage(values: Record<string, unknown>) {
    await this.page.addInitScript(values => {
      if (sessionStorage.getItem("__e2e_seeded")) return;
      sessionStorage.setItem("__e2e_seeded", "1");
      for (const [k, v] of Object.entries(values)) localStorage.setItem(k, JSON.stringify(v));
    }, values);
  }

  /** Open the app at a hash route ("" for none) and wait until the first board query has rendered. */
  async open(hash = "") {
    await this.page.goto(`./${hash}`);
    await this.ready();
  }

  /** The app has loaded the tracker and has no API request outstanding. Where the board is rendered
   *  (always in the old app, which renders it even on other pages), also wait for its first results. */
  async ready() {
    await expect.poll(() => this.api.answered.some(r => r.method === "GET" && r.path === "/api/tracker") && this.api.inflight === 0,
      { message: "app finished loading" }).toBe(true);
    const count = this.page.locator("#result-count");
    if (await count.count()) await expect(count).toHaveText(/internship/);
  }

  async reload() {
    await this.page.reload();
    await this.ready();
  }

  /** The custom dropdown button for a native <select> with this accessible name. */
  dropdown(name: string) {
    return this.page.getByRole("button", { name, exact: true });
  }

  async choose(dropdown: string, option: string) {
    await this.dropdown(dropdown).click();
    await this.page.getByRole("option", { name: option, exact: true }).click();
  }

  section(name: "board" | "tracker" | "companies" | "profile" | "tool" | "people") {
    return this.page.locator(`#${name}-view`);
  }

  nav(name: string) {
    return this.page.getByRole("navigation").getByRole("link", { name });
  }

  toast() {
    return this.page.getByRole("alert");
  }

  listing(company: string, title?: string) {
    const rows = this.page.locator("#listings article.listing").filter({ hasText: company });
    return title ? rows.filter({ hasText: title }) : rows;
  }

  card(company: string) {
    return this.page.locator("#kanban .card").filter({ hasText: company });
  }

  column(status: string) {
    return this.page.locator(`#kanban .column[data-status="${status}"]`);
  }

  drawer() {
    return this.page.locator("dialog#drawer");
  }
}
