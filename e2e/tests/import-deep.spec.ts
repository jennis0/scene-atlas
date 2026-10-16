import path from "path";
import { test, expect } from "../fixtures/base";
import {
  getSceneCount,
  getTestImagePaths,
  importFiles,
  openImportDialog,
  waitForGalleryLoad,
  waitForImportFinished,
} from "../helpers/actions";
import { IMAGE_DIR } from "../helpers/decrypt-fixtures";
import { writeUniquePng } from "../helpers/images";

test.describe("Import: end to end", () => {
  test("imports a new file, reports it, and undoes it", async ({ page }) => {
    test.setTimeout(180_000);
    const file = writeUniquePng("e2e-new-map.png");
    const label = path.basename(file);

    await page.goto("/");
    await waitForGalleryLoad(page);
    const before = await getSceneCount(page);

    await openImportDialog(page);
    await importFiles(page, [file]);

    // Progress view, titled with the import's label, then the outcome.
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: label })).toBeVisible();
    await expect(dialog.getByRole("progressbar")).toBeVisible();
    await waitForImportFinished(page);
    await expect(dialog.getByText("Finished. 1 imported.")).toBeVisible();

    // The new image lands in the gallery.
    await expect
      .poll(() => getSceneCount(page), { timeout: 30_000 })
      .toBe(before + 1);

    // Report: counts in the status line, then undo with confirmation.
    await dialog.getByRole("button", { name: "View report" }).click();
    const report = page.getByRole("dialog");
    await expect(report.getByRole("heading", { name: label })).toBeVisible();
    await expect(report.getByText(/^1 imported$/)).toBeVisible();
    await report.getByRole("button", { name: "Undo import" }).click();
    const confirm = page.getByRole("alertdialog", {
      name: "Undo this import?",
    });
    await expect(confirm).toContainText("1 image");
    await confirm
      .getByRole("button", { name: "Delete imported images" })
      .click();

    await expect(page.getByText("Import undone. 1 image removed.")).toBeVisible(
      { timeout: 10_000 },
    );
    await expect
      .poll(() => getSceneCount(page), { timeout: 30_000 })
      .toBe(before);
  });

  test("re-importing a library file is skipped as a duplicate", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const [existing] = getTestImagePaths(IMAGE_DIR, 1);
    test.skip(!existing, `No test images in ${IMAGE_DIR}`);

    await page.goto("/");
    await waitForGalleryLoad(page);
    const before = await getSceneCount(page);

    await openImportDialog(page);
    await importFiles(page, [existing]);
    await waitForImportFinished(page);

    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Finished. 0 imported, 1 already in your library."),
    ).toBeVisible();

    await dialog.getByRole("button", { name: "View report" }).click();
    const tab = page.getByRole("tab", { name: /Already in library/ });
    await expect(tab).toContainText("1");
    await tab.click();
    await expect(
      page.getByText("Identical to a file already in your library"),
    ).toBeVisible();
    await expect(
      page.getByTitle(path.basename(existing), { exact: true }),
    ).toBeVisible();

    // Nothing was added.
    expect(await getSceneCount(page)).toBe(before);
  });
});
