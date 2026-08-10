import { defineConfig, devices } from "@playwright/test";

/**
 * Basic smoke test config. The webServer boots the production build
 * (`npm run start`), which requires `npm run build` to have run first
 * (the CI workflow does this; locally run `npm run build` once).
 *
 * NEXT_PUBLIC_* vars are inlined at build time, so build with them set
 * (dummy values are fine — these tests only assert the app shell renders).
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
