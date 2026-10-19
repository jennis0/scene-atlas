import { test, expect } from "../fixtures/base";

test.describe("Gallery", () => {
  test("displays seeded images with count", async ({ page }) => {
    await page.goto("/");
    // Wait for the gallery to load — count shows "N scenes" (N > 0 means seeded)
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });
  });

  test("type tabs filter by image type", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 30_000,
    });

    // The tabs, not the tiles: a tile's name starts with its folder, which may be "Scenes"
    const tabs = page.getByRole("group", { name: "Image type" });

    // Click "Maps" tab
    await tabs.getByRole("button", { name: /Maps/ }).click();
    // URL should update with image_type filter
    await expect(page).toHaveURL(/image_type=battlemap/);

    // Click "Scenes" tab
    await tabs.getByRole("button", { name: /Scenes/ }).click();
    await expect(page).toHaveURL(/image_type=scene/);

    // Click "All" tab to reset — URL should no longer contain image_type
    await tabs.getByRole("button", { name: /All/ }).click();
    await expect(page).not.toHaveURL(/image_type=/);
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 5_000,
    });
  });

  test("view mode toggle switches between individual and grouped", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });

    // Switch to grouped view
    await page.getByTitle("Groups").click();
    // The view should change (grouped cards render differently)
    // Verify by switching back
    await page.getByTitle("Individual images").click();
  });

  test("sort dropdown changes ordering", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });

    // Open sort dropdown — find the sort trigger button
    const sortButton = page.getByRole("button", { name: /Newest|Oldest|Name/ });
    await sortButton.click();

    // Select "Name A–Z"
    await page.getByRole("menuitemradio", { name: /Name A/ }).click();

    // Sort button label should update to reflect the new sort
    await expect(page.getByRole("button", { name: /Name A/ })).toBeVisible();
  });
});
