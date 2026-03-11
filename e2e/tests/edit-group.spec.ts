import { test, expect } from "../fixtures/base";
import { waitForGalleryLoad, switchToGroupedView } from "../helpers/actions";

test.describe("Edit Group Dialog", () => {
  test("opens from group card context menu", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Switch to grouped view
    await switchToGroupedView(page);

    // Wait for group cards to appear
    const groupCard = page.getByTestId("group-card").first();
    await expect(groupCard).toBeVisible({ timeout: 10_000 });

    // Hover the card to reveal the three-dot menu button, then click it
    await groupCard.hover();
    const menuButton = groupCard
      .locator("button")
      .filter({ has: page.locator("svg") })
      .last();
    await menuButton.click();

    // Click "Edit" in the context menu
    await page.getByRole("menuitem", { name: /Edit/ }).click();

    // Verify the EditGroupDialog opens
    await expect(page.getByTestId("edit-group-dialog")).toBeVisible({
      timeout: 5_000,
    });
  });

  test("shows group images and metadata", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Switch to grouped view and open edit dialog
    await switchToGroupedView(page);

    const groupCard = page.getByTestId("group-card").first();
    await expect(groupCard).toBeVisible({ timeout: 10_000 });

    await groupCard.hover();
    const menuButton = groupCard
      .locator("button")
      .filter({ has: page.locator("svg") })
      .last();
    await menuButton.click();
    await page.getByRole("menuitem", { name: /Edit/ }).click();

    const dialog = page.getByTestId("edit-group-dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Verify images are listed (img elements or thumbnails within the dialog)
    await expect(dialog.locator("img").first()).toBeVisible({ timeout: 5_000 });

    // Verify group name is shown (input or heading containing the name)
    await expect(
      dialog.locator('input, h2, h3, [data-testid="group-name"]').first(),
    ).toBeVisible();

    // Close dialog
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });

  test("can close dialog with escape", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    // Switch to grouped view and open edit dialog
    await switchToGroupedView(page);

    const groupCard = page.getByTestId("group-card").first();
    await expect(groupCard).toBeVisible({ timeout: 10_000 });

    await groupCard.hover();
    const menuButton = groupCard
      .locator("button")
      .filter({ has: page.locator("svg") })
      .last();
    await menuButton.click();
    await page.getByRole("menuitem", { name: /Edit/ }).click();

    const dialog = page.getByTestId("edit-group-dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Press Escape to close
    await page.keyboard.press("Escape");

    // Verify dialog is hidden
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });
});
