import { test, expect } from "../fixtures/base";
import {
  IMPORT_START_TITLE,
  openImportDialog,
  waitForGalleryLoad,
} from "../helpers/actions";

test.describe("Import dialog: start view", () => {
  test("opens from the header and shows the pickers", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);
    await openImportDialog(page);

    await expect(page.getByText("Drop files or folders here")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Choose a folder" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Choose files" }),
    ).toBeVisible();
  });

  test("battlemap/scene choice toggles", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);
    await openImportDialog(page);

    const battlemaps = page.getByRole("button", { name: "Battlemaps" });
    const scenes = page.getByRole("button", { name: "Scenes", exact: true });
    await expect(battlemaps).toHaveAttribute("aria-pressed", "true");
    await expect(scenes).toHaveAttribute("aria-pressed", "false");
    await expect(
      page.getByText(/Grids are detected automatically/),
    ).toBeVisible();

    await scenes.click();
    await expect(scenes).toHaveAttribute("aria-pressed", "true");
    await expect(battlemaps).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByText(/No grid detection/)).toBeVisible();
  });

  test("closes with Escape", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);
    await openImportDialog(page);

    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("heading", { name: IMPORT_START_TITLE }),
    ).toBeHidden({ timeout: 5_000 });
  });
});
