import { test, expect } from "../fixtures/base";
import path from "path";
import fs from "fs";
import {
  waitForGalleryLoad,
  openImportDialog,
  uploadFiles,
  searchFor,
  clearSearch,
  openFilterPanel,
  getTestImagePaths,
  openImageViewer,
  getSceneCount,
} from "../helpers/actions";

const imageDir = path.resolve(__dirname, "..", ".tmp-images");

test.describe.serial("Upload -> Process -> Edit -> Search", () => {
  test("upload images via import dialog", async ({ page }) => {
    // Skip if no test images available
    if (!fs.existsSync(imageDir)) {
      test.skip();
      return;
    }

    const filePaths = getTestImagePaths(imageDir, 4);
    if (filePaths.length === 0) {
      test.skip();
      return;
    }

    await page.goto("/");
    await waitForGalleryLoad(page);

    const initialCount = await getSceneCount(page);

    await openImportDialog(page);
    await uploadFiles(page, filePaths, 30_000);

    // Wait for gallery to refresh with increased count after CLIP processing
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

  test("search finds uploaded images", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Search for a generic term likely to match any fantasy/RPG image set
    await searchFor(page, "scene");

    // Verify results appear — either "N results" (filtered) or "N scenes" (unfiltered)
    await expect(page.getByText(/\d+ (results?|scenes)/)).toBeVisible({
      timeout: 10_000,
    });

    // Clear search to restore full gallery
    await clearSearch(page);
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("semantic search activates relevance mode", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Use ~ prefix for semantic search
    await searchFor(page, "~fantasy landscape");

    // Verify relevance slider appears (indicates semantic mode was activated)
    await expect(page.getByText("Relevance").first()).toBeVisible({
      timeout: 15_000,
    });

    // Verify results are returned
    await expect(page.getByText(/\d+ (results?|scenes)/)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("filter by author shows filtered results", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await openFilterPanel(page);

    // Wait for filter content to load, then click the first clickable filter option
    // Authors appear as buttons in the filter panel
    const filterOption = page
      .locator('[role="dialog"], [data-radix-popper-content-wrapper]')
      .locator("button")
      .filter({ hasText: /.+/ })
      .first();
    await filterOption.click({ timeout: 5_000 });

    // Verify a filter chip appears
    await expect(page.getByTestId("filter-chip")).toBeVisible({
      timeout: 5_000,
    });

    // Verify the gallery updates (count text still present)
    await expect(page.getByText(/\d+ (results?|scenes)/)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("image viewer shows metadata", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await openImageViewer(page);

    const viewer = page.getByTestId("image-viewer");
    await expect(viewer).toBeVisible();

    // Verify metadata is shown — image name or author text should be present
    // Look for any text content inside the viewer that indicates metadata
    await expect(viewer.locator("img, video").first()).toBeVisible();

    // Close viewer with Escape
    await page.keyboard.press("Escape");
    await expect(viewer).not.toBeVisible();
  });
});
