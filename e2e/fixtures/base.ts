import { test as base } from "@playwright/test";
import { execSync } from "child_process";
import path from "path";
import { ensureTestImages } from "../helpers/decrypt-fixtures";
import { seedTestData } from "../helpers/seed";

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_URL = "http://localhost:8000";

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
              "Check that CLIP ONNX models are present in backend/models/clip-vit-b-32/",
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

      await use();
    },
    { scope: "worker", auto: true, timeout: 600_000 },
  ],
});

export { expect } from "@playwright/test";
