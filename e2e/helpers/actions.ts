import { Page, expect } from "@playwright/test";
import { listMediaFiles } from "./images";

/** Wait for the gallery to load and show a scene count. */
export async function waitForGalleryLoad(
  page: Page,
  timeout = 15_000,
): Promise<void> {
  await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({ timeout });
}

export const IMPORT_START_TITLE = "Import maps and scenes";

/** Open the import dialog (start view) via the header Import button. */
export async function openImportDialog(page: Page): Promise<void> {
  await page.getByTitle("Import images").click();
  await expect(
    page.getByRole("heading", { name: IMPORT_START_TITLE }),
  ).toBeVisible({ timeout: 5_000 });
}

/** Pick files in the start view; the import starts and the progress view opens. */
export async function importFiles(
  page: Page,
  filePaths: string[],
  timeout = 30_000,
): Promise<void> {
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files" }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(filePaths);
  await expect(
    page.getByRole("heading", { name: IMPORT_START_TITLE }),
  ).toBeHidden({ timeout });
}

/** Wait for the open progress view to say the import finished. */
export async function waitForImportFinished(
  page: Page,
  timeout = 120_000,
): Promise<void> {
  await expect(page.getByRole("dialog").getByText(/^Finished\./)).toBeVisible({
    timeout,
  });
}

/** From an open import report, undo the import and confirm. */
export async function undoImport(
  page: Page,
  imageCount: number,
): Promise<void> {
  const noun = imageCount === 1 ? "image" : "images";
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Undo import" })
    .click();
  const confirm = page.getByRole("alertdialog", { name: "Undo this import?" });
  await expect(confirm).toContainText(`${imageCount} ${noun}`);
  await confirm.getByRole("button", { name: "Delete imported images" }).click();
  await expect(
    page.getByText(`Import undone. ${imageCount} ${noun} removed.`),
  ).toBeVisible({ timeout: 10_000 });
}

/** Fill the search input and submit the search form. */
export async function searchFor(page: Page, query: string): Promise<void> {
  const searchInput = page.getByPlaceholder(/Search/);
  await searchInput.fill(query);
  await page.getByRole("button", { name: "Search", exact: true }).click();
}

/** Clear the search input and submit to restore full gallery. */
export async function clearSearch(page: Page): Promise<void> {
  const searchInput = page.getByPlaceholder(/Search/);
  await searchInput.clear();
  await page.getByRole("button", { name: "Search", exact: true }).click();
}

/** Switch to grouped view mode. */
export async function switchToGroupedView(page: Page): Promise<void> {
  await page.getByTitle("Groups").click();
}

/** Switch to individual view mode. */
export async function switchToIndividualView(page: Page): Promise<void> {
  await page.getByTitle("Individual images").click();
}

/** Open the filter panel popover. */
export async function openFilterPanel(page: Page): Promise<void> {
  await page.getByRole("button", { name: /Filters/ }).click();
}

/** Up to `maxFiles` still images under `imageDir`. */
export function getTestImagePaths(imageDir: string, maxFiles = 4): string[] {
  return listMediaFiles(imageDir)
    .filter((f) => /\.(jpe?g|png|webp)$/i.test(f))
    .slice(0, maxFiles);
}

/** Get the current scene count from the gallery. */
export async function getSceneCount(page: Page): Promise<number> {
  const text = await page.getByText(/\d+ scenes/).textContent();
  const match = text?.match(/(\d+)/);
  return match ? parseInt(match[1]) : 0;
}

/** Open the image viewer by clicking the first scene tile. */
export async function openImageViewer(page: Page): Promise<void> {
  const firstTile = page.getByTestId("scene-tile").first();
  await firstTile.click();
  await expect(page.getByTestId("image-viewer")).toBeVisible({
    timeout: 5_000,
  });
}
