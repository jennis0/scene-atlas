import { defineConfig, devices } from "@playwright/test";

// The docs screenshots (e2e/screenshots, design/brand.md#screenshots): drives a running demo
// instance and writes PNGs that scripts/demo/to_webp.py converts into docs/public/screenshots.
// Not part of the test suite: it needs the demo maps, which aren't in the repo.
export default defineConfig({
  testDir: "./screenshots",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // The import test sets its own, longer timeout
  timeout: 60_000,
  expect: { timeout: 15_000 },
  outputDir: "test-results-screenshots/runs",
  reporter: [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.DEMO_URL ?? "http://127.0.0.1:8123",
    // 1x, so maps in the gallery stay thumbnail-sized (design/brand.md)
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    // The docs site is always dark
    colorScheme: "dark",
  },
});
