import { defineConfig } from "@playwright/test";

// The packaged desktop app (e2e/packaged): run after building it, e.g.
//   uv run python scripts/build/build_electron.py --dev
//   npm run test:packaged
// No web servers: each test launches the app itself, which starts its own backend.
const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "./packaged",
  fullyParallel: false,
  forbidOnly: isCI,
  workers: 1,
  // Each test starts the app and the backend from cold, some twice.
  timeout: 5 * 60_000,
  outputDir: "test-results-packaged",
  reporter: isCI
    ? [["html", { open: "never", outputFolder: "playwright-report-packaged" }], ["github"]]
    : [["list"]],
});
