import { test as base } from "@playwright/test";
import { execSync } from "child_process";
import fs from "fs";
import path from "path";
import { seedTestData } from "../helpers/seed";

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const IMAGE_DIR = path.resolve(__dirname, "..", ".tmp-images");
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
      execSync("uv run python scripts/setup_models.py", {
        cwd: PROJECT_ROOT,
        stdio: "inherit",
      });

      // Generate test images if they don't already exist
      if (!fs.existsSync(IMAGE_DIR) || fs.readdirSync(IMAGE_DIR).length === 0) {
        fs.mkdirSync(IMAGE_DIR, { recursive: true });
        execSync(
          `uv run python scripts/generate_e2e_images.py --output-dir "${IMAGE_DIR}"`,
          { cwd: PROJECT_ROOT, stdio: "inherit" },
        );
      }

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
        await seedTestData(IMAGE_DIR);

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
              "Check that CLIP ONNX models are present in backend/models/fp16/",
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
