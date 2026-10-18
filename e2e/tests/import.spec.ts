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

  test("image type defaults to Auto and switches between types", async ({
    page,
  }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);
    await openImportDialog(page);

    const dialog = page.getByRole("dialog");
    const options = {
      Auto: /Sorts each image into battlemaps and scenes/,
      Battlemaps: /Grids are detected automatically/,
      Scenes: /No grid detection/,
    };
    const expectSelected = async (selected: keyof typeof options) => {
      for (const [name, hint] of Object.entries(options)) {
        await expect(
          dialog.getByRole("button", { name, exact: true }),
        ).toHaveAttribute("aria-pressed", String(name === selected));
        await expect(dialog.getByText(hint)).toBeVisible({
          visible: name === selected,
        });
      }
    };

    await expectSelected("Auto");
    for (const name of ["Battlemaps", "Scenes", "Auto"] as const) {
      await dialog.getByRole("button", { name, exact: true }).click();
      await expectSelected(name);
    }
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
