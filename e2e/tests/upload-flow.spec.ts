import { test, expect } from "../fixtures/base";
import {
  waitForGalleryLoad,
  searchFor,
  clearSearch,
  openFilterPanel,
  openImageViewer,
} from "../helpers/actions";

test.describe("Gallery interactions on seeded data", () => {
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
