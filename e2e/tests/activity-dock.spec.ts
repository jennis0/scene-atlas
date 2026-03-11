import { test, expect } from "../fixtures/base";
import fs from "fs";
import {
  waitForGalleryLoad,
  openImportDialog,
  uploadFiles,
  getTestImagePaths,
} from "../helpers/actions";
import { IMAGE_DIR } from "../helpers/decrypt-fixtures";

test.describe("Activity Dock", () => {
  test("dock pill appears after starting import", async ({ page }) => {
    // Skip if no test images available
    if (!fs.existsSync(IMAGE_DIR)) {
      test.skip();
      return;
    }

    const filePaths = getTestImagePaths(IMAGE_DIR, 2);
    if (filePaths.length === 0) {
      test.skip();
      return;
    }

    await page.goto("/");
    await waitForGalleryLoad(page);

    // Open import dialog and upload files
    await openImportDialog(page);
    await uploadFiles(page, filePaths, 30_000);

    // After dialog closes, verify the dock pill appears
    await expect(page.getByTestId("activity-dock-pill")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("expanding dock shows job cards", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    const dockPill = page.getByTestId("activity-dock-pill");

    // Check if dock pill is already visible (from previous import or active jobs)
    const pillVisible = await dockPill.isVisible().catch(() => false);

    if (!pillVisible) {
      // No active jobs — start an import to make the dock appear
      if (!fs.existsSync(IMAGE_DIR)) {
        test.skip();
        return;
      }

      const filePaths = getTestImagePaths(IMAGE_DIR, 2);
      if (filePaths.length === 0) {
        test.skip();
        return;
      }

      await openImportDialog(page);
      await uploadFiles(page, filePaths, 30_000);

      // Wait for dock pill to appear
      await expect(dockPill).toBeVisible({ timeout: 15_000 });
    }

    // Click the dock pill to expand it
    await dockPill.click();

    // Verify the dock panel is visible
    await expect(page.getByTestId("activity-dock-panel")).toBeVisible({
      timeout: 5_000,
    });

    // Verify at least one job card is visible
    await expect(page.getByTestId("import-job-card").first()).toBeVisible({
      timeout: 5_000,
    });
  });
});
