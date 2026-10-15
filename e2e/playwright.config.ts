import { defineConfig, devices } from "@playwright/test";

// The suite runs against whichever frontend APP_URL points at. Without APP_URL it serves the
// current frontend (board/static) as plain files; no backend runs, and every /api call is mocked.
const DEFAULT_PORT = 8781;
const APP_URL = process.env.APP_URL || `http://127.0.0.1:${DEFAULT_PORT}/`;
const serveOldFrontend = !process.env.APP_URL;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: APP_URL,
    locale: "en-US",
    timezoneId: "America/Toronto",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: serveOldFrontend
    ? {
        command: `python3 -m http.server ${DEFAULT_PORT} --bind 127.0.0.1 --directory ../board/static`,
        url: APP_URL,
        reuseExistingServer: !process.env.CI,
        stdout: "ignore",
        stderr: "ignore",
      }
    : undefined,
});
