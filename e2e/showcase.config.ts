import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Screenshots and recordings for docs/showcase/SHOWCASE.md. Same mocked API and made-up fixtures
// as the tests; nothing reaches the real database, Claude or Prospeo.
// Run: npx playwright test -c showcase.config.ts
export default defineConfig({
  ...base,
  testDir: "./showcase",
  outputDir: "./showcase-results",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  reporter: [["list"]],
  use: {
    ...base.use,
    video: { mode: "on", size: { width: 1440, height: 900 } },
    launchOptions: { slowMo: 120 },
  },
});
