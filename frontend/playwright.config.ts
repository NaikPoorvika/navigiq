import { defineConfig, devices } from "@playwright/test";

/**
 * NQ-026 end-to-end tests. They drive the real app in a real browser.
 * Start the app first (scripts\dev.ps1) - the planning test uses the real
 * backend and database; the error tests fake the backend's replies.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env["NAVIGIQ_URL"] ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
