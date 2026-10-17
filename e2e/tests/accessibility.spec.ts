import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures/base";
import { switchToGroupedView, waitForGalleryLoad } from "../helpers/actions";

/**
 * WCAG 2.2 AA checks: an axe scan of each main surface in both themes, and the
 * keyboard path through the core task (find an image, open it, close it).
 */

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function expectNoViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_TAGS)
    .analyze();
  const summary = violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.nodes.length} node(s), e.g. ${v.nodes[0]?.target.join(" ")}`,
  );
  expect(summary).toEqual([]);
}

for (const theme of ["dark", "light"] as const) {
  test.describe(`axe scan, ${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t) => {
        localStorage.setItem("scene-atlas-theme", t);
      }, theme);
      await page.goto("/");
      await waitForGalleryLoad(page);
    });

    test("gallery, individual view", async ({ page }) => {
      await expectNoViolations(page);
    });

    test("gallery, grouped view", async ({ page }) => {
      await switchToGroupedView(page);
      await expect(page.getByTestId("group-card").first()).toBeVisible();
      await expectNoViolations(page);
    });

    test("image viewer", async ({ page }) => {
      await page.getByTestId("scene-tile").first().getByRole("button").click();
      await expect(page.getByTestId("image-viewer")).toBeVisible();
      await expectNoViolations(page);
    });

    test("filter panel", async ({ page }) => {
      await page.getByRole("button", { name: /Filters/ }).click();
      await expect(page.getByTestId("filter-popover")).toBeVisible();
      await expectNoViolations(page);
    });

    test("tag management dialog", async ({ page }) => {
      await page.getByRole("button", { name: "Manage tags" }).click();
      await expect(
        page.getByRole("dialog", { name: "Tag Management" }),
      ).toBeVisible();
      await expectNoViolations(page);
    });

    test("library and settings dialog", async ({ page }) => {
      await page.getByTitle("Library information").click();
      const dialog = page.getByRole("dialog", { name: "Library" });
      await expect(dialog).toBeVisible();
      await expectNoViolations(page);
      await dialog.getByRole("tab", { name: "Settings" }).click();
      await expectNoViolations(page);
    });
  });
}

test.describe("keyboard", () => {
  test("opens an image from the gallery and returns to it on close", async ({
    page,
  }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);

    const firstTile = page
      .getByTestId("scene-tile")
      .first()
      .getByRole("button");
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press("Tab");
      if (await firstTile.evaluate((el) => el === document.activeElement))
        break;
    }
    await expect(firstTile).toBeFocused();

    await page.keyboard.press("Enter");
    const viewer = page.getByRole("dialog").first();
    await expect(viewer).toBeVisible();
    await expect(viewer).toBeFocused();

    // Focus stays inside the viewer
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(
        () =>
          !!document.activeElement?.closest('[data-testid="image-viewer"]') ||
          document.activeElement === document.body,
      );
      expect(inside).toBe(true);
    }

    await page.keyboard.press("Escape");
    await expect(page.getByTestId("image-viewer")).toBeHidden();
    await expect(firstTile).toBeFocused();
  });

  test("a skip link moves focus to the results", async ({ page }) => {
    await page.goto("/");
    await waitForGalleryLoad(page);
    await page.keyboard.press("Tab");
    const skip = page.getByRole("button", { name: "Skip to results" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#results")).toBeFocused();
  });
});
