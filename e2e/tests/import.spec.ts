import { test, expect } from "../fixtures/base";
import path from "path";
import fs from "fs";
import { getTestImagePaths, IMPORT_DIALOG_TITLE } from "../helpers/actions";

test.describe("Import flow", () => {
  test("import dialog opens and shows upload UI", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("Scene Atlas");

    // Click the Import button (has title="Import images")
    await page.getByTitle("Import images").click();

    // The import dialog should open
    await expect(
      page.getByRole("heading", { name: IMPORT_DIALOG_TITLE }),
    ).toBeVisible({ timeout: 5_000 });

    // Should show upload controls
    await expect(page.getByText(/Drop files or folders here/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Choose files" }),
    ).toBeVisible();
  });

  test("upload a file and see it in preview", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("Scene Atlas");

    // Open import dialog
    await page.getByTitle("Import images").click();
    await expect(
      page.getByRole("heading", { name: IMPORT_DIALOG_TITLE }),
    ).toBeVisible({ timeout: 5_000 });

    // Find a test image to upload
    const imageDir =
      process.env.E2E_IMAGE_DIR || path.resolve(__dirname, "..", ".tmp-images");

    const testFiles = getTestImagePaths(imageDir, 1);
    if (testFiles.length === 0) {
      if (process.env.CI)
        throw new Error(`No test images found in ${imageDir}`);
      test.skip();
      return;
    }

    // Use the file chooser to upload
    const fileChooserPromise = page.waitForEvent("filechooser");

    // Click the "Choose files" button to trigger file chooser
    await page.getByRole("button", { name: "Choose files" }).click();

    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(testFiles[0]);

    // Once the import has been created, sealed and is uploading, the dialog
    // replaces its start view with the job's progress view.
    await expect(
      page.getByRole("heading", { name: IMPORT_DIALOG_TITLE }),
    ).toBeHidden({ timeout: 30_000 });
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});
