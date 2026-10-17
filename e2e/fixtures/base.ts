import { test as base } from "@playwright/test";
import { execSync } from "child_process";
import path from "path";
import { ensureTestImages } from "../helpers/decrypt-fixtures";
import { seedTestData } from "../helpers/seed";
import { BACKEND_URL } from "../helpers/config";

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");

/**
 * Extended test fixture that automatically seeds test data once per worker.
 * Since workers: 1, this seeds exactly once for the entire test run.
 *
 * All test files should import { test, expect } from this module
 * instead of from '@playwright/test'.
 */
export const test = base.extend<object, { seedData: void }>({
  seedData: [
    async ({}, use) => {
      // playwright.config.ts points the backend at a per-run temp directory.
      // Refuse to seed if that didn't happen, rather than import into a real library.
      if (!process.env.E2E_RUN_DIR || !process.env.APP_DATA_DIR) {
        throw new Error(
          "E2E_RUN_DIR / APP_DATA_DIR not set: run the tests through e2e/playwright.config.ts",
        );
      }

      // Ensure CLIP ONNX models are present (idempotent, downloads if missing)
      execSync("uv run python scripts/models/setup_models.py", {
        cwd: PROJECT_ROOT,
        stdio: "inherit",
      });

      // Decrypt and extract test images if not already present
      const imageDir = ensureTestImages();

      // Check if data is already seeded (images exist in the backend)
      console.log("[fixture] Checking backend for existing data...");
      const checkRes = await fetch(`${BACKEND_URL}/api/v1/search/facets`);
      const facets = await checkRes.json();
      console.log(
        `[fixture] Pre-seed facets: total_images=${facets.total_images}`,
      );

      if (facets.total_images === 0) {
        console.log("[fixture] No data found — running seed...");
        // Seed test data via the import API
        await seedTestData(imageDir);

        // Verify seeding succeeded — pipeline must have run with CLIP models
        console.log("[fixture] Verifying seed result...");
        const verifyRes = await fetch(`${BACKEND_URL}/api/v1/search/facets`);
        const verifyFacets = await verifyRes.json();
        console.log(
          `[fixture] Post-seed facets: ${JSON.stringify(verifyFacets)}`,
        );
        if (verifyFacets.total_images === 0) {
          throw new Error(
            "Seeding failed: no images found in DB after import completed. " +
              "Check that the ONNX model is present (E2E_MODELS_DIR, default data/models/).",
          );
        }
        console.log(
          `[fixture] Seed verified: ${verifyFacets.total_images} image(s) in DB.`,
        );
      } else {
        console.log(
          `[fixture] Data already present (${facets.total_images} images) — skipping seed.`,
        );
      }

      // Mark setup as complete so the app skips the setup wizard
      const setupRes = await fetch(
        `${BACKEND_URL}/api/v1/models/setup-complete`,
        { method: "POST" },
      );
      if (!setupRes.ok) {
        console.warn(
          `[fixture] Warning: failed to mark setup complete (${setupRes.status})`,
        );
      }

      await use();
    },
    { scope: "worker", auto: true, timeout: 600_000 },
  ],
});

export { expect } from "@playwright/test";
