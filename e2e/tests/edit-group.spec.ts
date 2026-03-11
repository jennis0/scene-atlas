import { test, expect } from "../fixtures/base";
import { waitForGalleryLoad, switchToGroupedView } from "../helpers/actions";
import { Page } from "@playwright/test";

/** Navigate to grouped view and open the EditGroupDialog for the first group. */
async function openEditDialogForFirstGroup(page: Page) {
  await page.goto("/");
  await waitForGalleryLoad(page);
  await switchToGroupedView(page);

  const groupCard = page.getByTestId("group-card").first();
  await expect(groupCard).toBeVisible({ timeout: 10_000 });

  await groupCard.hover();
  await groupCard.getByTestId("group-card-menu").click();
  await page.getByRole("menuitem", { name: /Edit/ }).click();

  const dialog = page.getByTestId("edit-group-dialog");
  await expect(dialog).toBeVisible({ timeout: 5_000 });
  return dialog;
}

test.describe("Edit Group Dialog", () => {
  test("opens from group card context menu", async ({ page }) => {
    const dialog = await openEditDialogForFirstGroup(page);
    await expect(dialog).toBeVisible();
  });

  test("shows group images and metadata", async ({ page }) => {
    const dialog = await openEditDialogForFirstGroup(page);

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
    const dialog = await openEditDialogForFirstGroup(page);

    // Press Escape to close
    await page.keyboard.press("Escape");

    // Verify dialog is hidden
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });
});
