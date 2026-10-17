import { test, expect } from "../fixtures/base";
import fs from "fs";
import {
  waitForGalleryLoad,
  openImportDialog,
  uploadFiles,
  getTestImagePaths,
  IMPORT_DIALOG_TITLE,
} from "../helpers/actions";
import { IMAGE_DIR } from "../helpers/decrypt-fixtures";

test.describe("Import Deep", () => {
  test("import dialog shows upload controls", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Open import dialog
    await openImportDialog(page);

    // Verify drop zone is visible
    await expect(page.getByText(/Drop files or folders here/)).toBeVisible();

    // Verify browse buttons are visible
    await expect(
      page.getByRole("button", { name: "Choose files" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Choose a folder" }),
    ).toBeVisible();

    // Close dialog
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("heading", { name: IMPORT_DIALOG_TITLE }),
    ).not.toBeVisible({ timeout: 5_000 });
  });

  test("default type toggle is visible", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await openImportDialog(page);

    // Verify the "Import these as" toggle (Battlemaps / Scenes) is visible
    const dialog = page.getByRole("dialog");
    const mapsButton = dialog.getByRole("button", { name: "Battlemaps" });
    const scenesButton = dialog.getByRole("button", { name: "Scenes" });

    await expect(mapsButton).toBeVisible({ timeout: 5_000 });
    await expect(scenesButton).toBeVisible({ timeout: 5_000 });

    // Both buttons should be present and interactable
    await expect(mapsButton).toBeEnabled();
    await expect(scenesButton).toBeEnabled();

    // Close dialog
    await page.keyboard.press("Escape");
  });

  test("file upload triggers processing", async ({ page }) => {
    test.setTimeout(180_000);
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

    // Verify the activity dock pill appears (import processing started)
    await expect(page.getByTestId("activity-dock-pill")).toBeVisible({
      timeout: 15_000,
    });
  });
});
