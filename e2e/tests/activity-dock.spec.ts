import path from "path";
import { test, expect } from "../fixtures/base";
import {
  importFiles,
  openImportDialog,
  waitForGalleryLoad,
} from "../helpers/actions";
import { writeUniquePng } from "../helpers/images";

test.describe("Activity Dock", () => {
  test("shows an import and opens its report", async ({ page }) => {
    test.setTimeout(180_000);
    // Named per attempt: a retry's dock still lists the failed attempt's import.
    const file = writeUniquePng(`e2e-dock-map-${test.info().retry}.png`);
    const label = path.basename(file);

    await page.goto("/");
    await waitForGalleryLoad(page);
    await openImportDialog(page);
    await importFiles(page, [file], { as: "Battlemaps" });

    // Closing the dialog never stops the import; the dock keeps it.
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Close" })
      .first()
      .click();
    const pill = page.getByTestId("activity-dock-pill");
    await expect(pill).toBeVisible({ timeout: 15_000 });

    await pill.click();
    await expect(page.getByTestId("activity-dock-panel")).toBeVisible();
    const card = page.getByTestId("import-job-card").filter({ hasText: label });
    await expect(card).toBeVisible();
    await expect(card).toContainText("1 imported", { timeout: 120_000 });

    // A clean finished import opens straight in the group editor.
    await card.getByRole("button", { name: new RegExp(label) }).click();
    await expect(page.getByTestId("edit-group-dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("edit-group-dialog")).toBeHidden();

    // Undo from the dock row, after confirming, to clean up.
    await pill.click();
    await card.hover();
    await card.getByRole("button", { name: "Undo import" }).click();
    const confirm = page.getByRole("dialog", { name: "Undo this import?" });
    await expect(confirm).toContainText("1 image");
    await confirm
      .getByRole("button", { name: "Delete imported images" })
      .click();
    await expect(page.getByText("Import undone. 1 image removed.")).toBeVisible(
      {
        timeout: 10_000,
      },
    );
  });
});
