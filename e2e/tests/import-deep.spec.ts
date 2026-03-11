import { test, expect } from "../fixtures/base";
import path from "path";
import fs from "fs";
import {
  waitForGalleryLoad,
  openImportDialog,
  uploadFiles,
  getTestImagePaths,
  getSceneCount,
} from "../helpers/actions";

const imageDir = path.resolve(__dirname, "..", ".tmp-images");

test.describe("Import Deep", () => {
  test("import dialog shows upload controls", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Open import dialog
    await openImportDialog(page);

    // Verify drop zone is visible
    await expect(page.getByText(/Drop files or folders here/)).toBeVisible();

    // Verify browse buttons are visible
    await expect(page.getByText("Browse files")).toBeVisible();
    await expect(page.getByText("Browse folder")).toBeVisible();

    // Close dialog
    await page.keyboard.press("Escape");
    await expect(page.getByText("Import Scenes")).not.toBeVisible({
      timeout: 5_000,
    });
  });

  test("default type toggle is visible", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await openImportDialog(page);

    // Verify type toggle buttons are visible
    const battlemapButton = page.getByRole("button", { name: "Battlemap" });
    const sceneButton = page.getByRole("button", { name: "Scene" });

    await expect(battlemapButton).toBeVisible({ timeout: 5_000 });
    await expect(sceneButton).toBeVisible({ timeout: 5_000 });

    // Battlemap should be the default (active state — check for aria-pressed or a distinguishing class)
    // At minimum, both buttons should be present and interactable
    await expect(battlemapButton).toBeEnabled();
    await expect(sceneButton).toBeEnabled();

    // Close dialog
    await page.keyboard.press("Escape");
  });

  test("file upload triggers processing", async ({ page }) => {
    // Skip if no test images available
    if (!fs.existsSync(imageDir)) {
      test.skip();
      return;
    }

    const filePaths = getTestImagePaths(imageDir, 2);
    if (filePaths.length === 0) {
      test.skip();
      return;
    }

    await page.goto("/");
    await waitForGalleryLoad(page);

    const initialCount = await getSceneCount(page);

    // Open import dialog and upload files
    await openImportDialog(page);
    await uploadFiles(page, filePaths, 30_000);

    // Wait for gallery count to reflect new images after CLIP processing
    await page.waitForFunction(
      (expected) => {
        const countText = document.body.innerText.match(/(\d+)\s+scenes/);
        if (!countText) return false;
        return parseInt(countText[1]) > expected;
      },
      initialCount,
      { timeout: 120_000 },
    );

    const newCount = await getSceneCount(page);
    expect(newCount).toBeGreaterThan(initialCount);
  });
});
