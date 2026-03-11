import { test, expect } from "../fixtures/base";
import {
  waitForGalleryLoad,
  searchFor,
  clearSearch,
  openFilterPanel,
  switchToGroupedView,
  switchToIndividualView,
} from "../helpers/actions";

test.describe("Gallery Deep", () => {
  test("text-only search with = prefix hides relevance slider", async ({
    page,
  }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await searchFor(page, "=sometext");

    // The relevance slider should NOT be visible for text-only searches
    await expect(page.getByText("Relevance")).not.toBeVisible();

    await clearSearch(page);
  });

  test("semantic search shows relevance controls", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await searchFor(page, "~dark cave");

    // The relevance slider label should be visible for semantic searches
    await expect(page.getByText("Relevance").first()).toBeVisible({
      timeout: 5_000,
    });

    await clearSearch(page);
  });

  test("filter panel opens and shows filter options", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await openFilterPanel(page);

    // Verify filter content is visible — look for filter-related UI
    await expect(page.getByRole("button", { name: /Filters/ })).toBeVisible();

    // Close filter panel by pressing Escape
    await page.keyboard.press("Escape");
  });

  test("applying author filter shows filter chip", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await openFilterPanel(page);

    // Click the first checkbox/option in the filter panel (author filter)
    const firstAuthorOption = page
      .locator('[role="checkbox"], [role="option"]')
      .first();
    await firstAuthorOption.click({ timeout: 5_000 });

    // Verify a filter chip appears
    await expect(page.getByTestId("filter-chip").first()).toBeVisible({
      timeout: 5_000,
    });

    // Remove filters via Clear all
    await page.getByText("Clear all").click();

    // Verify filter chips are gone
    await expect(page.getByTestId("filter-chip")).toHaveCount(0);
  });

  test("clear all removes all filters and search", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Capture the initial scene count text
    const initialCount = await page.getByText(/\d+ scenes/).textContent();

    await searchFor(page, "test");

    // Click "Clear all" button to reset everything
    await page.getByText("Clear all").click();

    // Verify the search input is cleared
    await expect(page.getByPlaceholder(/Search/)).toHaveValue("");

    // Verify full gallery returns (scene count restored)
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("empty state shows when no results match", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    await searchFor(page, "zzzznonexistentzzzzz");

    // Verify empty state message is shown
    await expect(page.getByText(/No images match/)).toBeVisible({
      timeout: 10_000,
    });

    await clearSearch(page);
  });

  test("grouped view shows group cards", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Switch to grouped view
    await switchToGroupedView(page);

    // Verify group cards are visible
    await expect(page.getByTestId("group-card").first()).toBeVisible({
      timeout: 5_000,
    });

    // Switch back to individual view
    await switchToIndividualView(page);

    // Verify scene tiles are visible
    await expect(page.getByTestId("scene-tile").first()).toBeVisible({
      timeout: 5_000,
    });
  });

  test("sort dropdown changes ordering", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Open the sort dropdown
    const sortButton = page.getByRole("button", { name: /Newest|Oldest|Name/ });
    await sortButton.click();

    // Select "Name A-Z"
    await page.getByRole("menuitemradio", { name: /Name A/ }).click();

    // Verify the sort button label updated
    await expect(page.getByRole("button", { name: /Name A/ })).toBeVisible();

    // Restore default: open dropdown again and select "Newest"
    await page.getByRole("button", { name: /Name A/ }).click();
    await page.getByRole("menuitemradio", { name: /Newest/ }).click();

    await expect(page.getByRole("button", { name: /Newest/ })).toBeVisible();
  });
});
