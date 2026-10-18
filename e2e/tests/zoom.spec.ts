import { test, expect } from "../fixtures/base";
import type { Locator, Page } from "@playwright/test";

/**
 * WCAG 1.4.4 (resize text): at 200% zoom nothing is lost. Playwright can't set browser
 * zoom, but zoom only shrinks the viewport in CSS px: 200% on a 1920x1080 screen leaves
 * about 960x480 once the browser's own toolbars are taken off. The Larger text size on
 * top makes it harsher than zoom alone.
 */
test.use({ viewport: { width: 960, height: 480 } });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("scene-atlas-text-size", "larger"),
  );
  await page.goto("/");
  await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
    timeout: 15_000,
  });
});

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

/** Fully on screen, not just partly visible. */
async function expectOnScreen(locator: Locator) {
  await expect(locator).toBeInViewport({ ratio: 1 });
}

test.describe("200% zoom with Larger text", () => {
  test("gallery: header controls on screen, grid still visible", async ({
    page,
  }) => {
    await expectNoHorizontalScroll(page);
    await expectOnScreen(page.getByRole("button", { name: "Import" }));
    await expectOnScreen(page.getByTitle("Library information"));
    await expectOnScreen(page.getByPlaceholder(/Search scenes/));

    // The compact header leaves at least half the window for the maps
    const header = await page.locator("header").boundingBox();
    expect(header!.height).toBeLessThanOrEqual(480 / 2);
    await expect(page.getByTestId("scene-tile").first()).toBeInViewport();
  });

  test("image viewer: close stays on screen, details and scenes reachable", async ({
    page,
  }) => {
    await page.getByTestId("scene-tile").first().click();
    const viewer = page.getByTestId("image-viewer");
    await expect(viewer).toBeVisible();
    await expectNoHorizontalScroll(page);

    await expectOnScreen(viewer.getByRole("button", { name: "Close" }));
    // Everything in the details panel can be scrolled to
    const typeToggle = viewer.getByRole("button", { name: "Scene" }).first();
    await typeToggle.scrollIntoViewIfNeeded();
    await expectOnScreen(typeToggle);
  });

  test("library dialog fits, every tab usable", async ({ page }) => {
    await page.getByTitle("Library information").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    for (const tab of ["Library", "Appearance", "Settings"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expectNoHorizontalScroll(page);
      await expectOnScreen(page.getByRole("tab", { name: tab }));
      await expectOnScreen(dialog.getByRole("button", { name: "Close" }));
    }

    // The last Appearance control can be scrolled to and used
    await page.getByRole("tab", { name: "Appearance" }).click();
    const lastPalette = page.getByRole("radio", { name: /Plum/ });
    await lastPalette.scrollIntoViewIfNeeded();
    await expectOnScreen(lastPalette);
  });

  test("import dialog: the file pickers can be reached", async ({ page }) => {
    await page.getByRole("button", { name: "Import" }).click();
    const dialog = page.getByRole("dialog");
    await expectOnScreen(dialog.getByRole("button", { name: "Close" }));
    const chooseFiles = dialog.getByRole("button", { name: "Choose files" });
    await chooseFiles.scrollIntoViewIfNeeded();
    await expectOnScreen(chooseFiles);
  });
});
