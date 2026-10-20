import { defineConfig } from "@playwright/test";

// The upgrade test (e2e/upgrade, design/testing.md#upgrade-test): installs an older build,
// updates it to the new one and compares the library before and after. Run by the Release
// workflow on Windows; see the top of upgrade.spec.ts for what it needs.
const isCI = !!process.env.CI;
// The Release workflow runs it twice (from a 0.0.0 build and from the last release).
const htmlReport = process.env.UPGRADE_PLAYWRIGHT_REPORT ?? "playwright-report-upgrade";

export default defineConfig({
  testDir: "./upgrade",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  forbidOnly: isCI,
  workers: 1,
  retries: 0,
  timeout: 90 * 60_000,
  outputDir: "test-results-upgrade",
  reporter: isCI
    ? [["html", { open: "never", outputFolder: htmlReport }], ["github"]]
    : [["list"]],
});
