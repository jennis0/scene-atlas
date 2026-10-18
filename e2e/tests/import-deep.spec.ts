import path from "path";
import { test, expect } from "../fixtures/base";
import {
  getSceneCount,
  getTestImagePaths,
  importFiles,
  openImportDialog,
  undoImport,
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
    await importFiles(page, [file], { as: "Battlemaps" });

    // Progress view, titled with the import's label, then the result in place.
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: label })).toBeVisible();
    await expect(dialog.getByRole("progressbar")).toBeVisible();
    await waitForImportFinished(page);
    await expect(dialog.getByText(/^1 imported in 1 group/)).toBeVisible();

    await expect
      .poll(() => getSceneCount(page), { timeout: 30_000 })
      .toBe(before + 1);

    await expect(dialog.getByRole("heading", { name: label })).toBeVisible();
    await undoImport(page, 1);
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
      dialog.getByText(/^0 imported, 1 already in your library/),
    ).toBeVisible();

    const tab = page.getByRole("tab", { name: /Already in library/ });
    await expect(tab).toContainText("1");
    await tab.click();
    await expect(
      page.getByText("Identical to a file already in your library"),
    ).toBeVisible();
    await expect(
      page.getByTitle(path.basename(existing), { exact: true }),
    ).toBeVisible();

    expect(await getSceneCount(page)).toBe(before);
  });
});
