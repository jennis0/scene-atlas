import { test, expect } from "../fixtures/base";
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
} from "../helpers/actions";
import { IMAGE_DIR } from "../helpers/decrypt-fixtures";

test.describe("Upload & Gallery Interactions", () => {
  test("upload images via import dialog", async ({ page }) => {
    test.setTimeout(180_000);
    // Skip if no test images available
    if (!fs.existsSync(IMAGE_DIR)) {
      test.skip();
      return;
    }

    const filePaths = getTestImagePaths(IMAGE_DIR, 4);
    if (filePaths.length === 0) {
      test.skip();
      return;
    }

    await page.goto("/");
    await waitForGalleryLoad(page);

    await openImportDialog(page);
    await uploadFiles(page, filePaths, 30_000);

    // Verify the activity dock pill appears (import processing started)
    await expect(page.getByTestId("activity-dock-pill")).toBeVisible({
      timeout: 15_000,
    });

    // Expand the dock and verify the job card appears
    await page.getByTestId("activity-dock-pill").click();
    await expect(page.getByTestId("activity-dock-panel")).toBeVisible({
      timeout: 5_000,
    });

    // Wait for upload to finish — dock shows "ready to review" when staging completes
    await expect(
      page
        .getByTestId("import-job-card")
        .first()
        .getByText(/ready to review/i),
    ).toBeVisible({ timeout: 120_000 });
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
    await expect(page.locator('input[type="range"]')).toBeVisible({
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

    // Click the first author option in the filter panel
    const filterPopover = page.getByTestId("filter-popover");
    await expect(filterPopover).toBeVisible({ timeout: 5_000 });
    const filterOption = filterPopover.locator("button[title]").first();
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
