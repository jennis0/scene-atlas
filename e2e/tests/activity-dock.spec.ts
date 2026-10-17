import path from "path";
import { test, expect } from "../fixtures/base";
import {
  importFiles,
  openImportDialog,
  undoImport,
  waitForGalleryLoad,
} from "../helpers/actions";
import { writeUniquePng } from "../helpers/images";

test.describe("Activity Dock", () => {
  test("shows an import and opens its report", async ({ page }) => {
    test.setTimeout(180_000);
    const file = writeUniquePng("e2e-dock-map.png");
    const label = path.basename(file);

    await page.goto("/");
    await waitForGalleryLoad(page);
    await openImportDialog(page);
    await importFiles(page, [file]);

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

    // A finished import opens its report; clean up by undoing it.
    await card.getByRole("button", { name: new RegExp(label) }).click();
    const report = page.getByRole("dialog");
    await expect(report.getByRole("heading", { name: label })).toBeVisible();
    await undoImport(page, 1);
  });
});
