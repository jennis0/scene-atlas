import { Page, expect } from "@playwright/test";
import path from "path";
import fs from "fs";

/** Wait for the gallery to load and show a scene count. */
export async function waitForGalleryLoad(
  page: Page,
  timeout = 15_000,
): Promise<void> {
  await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({ timeout });
}

/** Heading of the import dialog's start view (before files are chosen). */
export const IMPORT_DIALOG_TITLE = "Import maps and scenes";

/** Open the import dialog via the Import button. */
export async function openImportDialog(page: Page): Promise<void> {
  await page.getByTitle("Import images").click();
  await expect(
    page.getByRole("heading", { name: IMPORT_DIALOG_TITLE }),
  ).toBeVisible({ timeout: 5_000 });
}

/**
 * Upload files via the file chooser in the import dialog.
 * Assumes the import dialog is already open.
 *
 * Once the import has started the dialog switches to the job's progress view;
 * this then closes the dialog (the import carries on, shown in the activity dock).
 */
export async function uploadFiles(
  page: Page,
  filePaths: string[],
  timeout = 30_000,
): Promise<void> {
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files" }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(filePaths);

  // The start view is replaced by the progress view when the import starts.
  await expect(
    page.getByRole("heading", { name: IMPORT_DIALOG_TITLE }),
  ).toBeHidden({ timeout });
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).first().click();
  await expect(dialog).toBeHidden({ timeout: 5_000 });
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

/**
 * Hover a parent element then click a child within it.
 * Useful for elements with opacity-0 group-hover:opacity-100.
 */
export async function hoverAndClick(
  page: Page,
  parentLocator: ReturnType<Page["locator"]>,
  childLocator: ReturnType<Page["locator"]>,
): Promise<void> {
  await parentLocator.hover();
  await childLocator.click();
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

/**
 * Collect a subset of test image paths for upload.
 * Returns up to `maxFiles` image paths from the test image directory.
 */
export function getTestImagePaths(imageDir: string, maxFiles = 4): string[] {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (files.length >= maxFiles) return;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (/\.(jpe?g|png|webp)$/i.test(entry.name)) {
        files.push(full);
      }
    }
  };
  walk(imageDir);
  return files;
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
