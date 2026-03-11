import { test, expect } from "../fixtures/base";

test.describe("Image Viewer", () => {
  test("clicking an image opens the viewer modal", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });

    // Click the first image thumbnail
    const firstTile = page.getByTestId("scene-tile").first();
    await firstTile.click();

    // The ImageViewer overlay should appear
    const viewer = page.getByTestId("image-viewer");
    await expect(viewer).toBeVisible({ timeout: 5_000 });
  });

  test("escape key closes the viewer", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });

    // Open the viewer
    const firstTile = page.getByTestId("scene-tile").first();
    await firstTile.click();

    const viewer = page.getByTestId("image-viewer");
    await expect(viewer).toBeVisible({ timeout: 5_000 });

    // Press Escape
    await page.keyboard.press("Escape");

    // Viewer should close
    await expect(viewer).not.toBeVisible();
  });

  test("arrow keys navigate between images", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });

    // Open the viewer on the first image
    const firstTile = page.getByTestId("scene-tile").first();
    await firstTile.click();

    const viewer = page.getByTestId("image-viewer");
    await expect(viewer).toBeVisible({ timeout: 5_000 });

    // Capture the current image src
    const viewerImg = viewer.locator("img").first();
    const initialSrc = await viewerImg.getAttribute("src");

    // Navigate forward with arrow key
    await page.keyboard.press("ArrowRight");

    // The displayed image should change
    await expect(viewerImg).not.toHaveAttribute("src", initialSrc!);

    // Navigate back
    await page.keyboard.press("ArrowLeft");

    // Should return to the original image
    await expect(viewerImg).toHaveAttribute("src", initialSrc!);
  });

  test("deleting an image shows the next image instead of closing viewer", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });

    // Open the viewer on the first image
    const firstTile = page.getByTestId("scene-tile").first();
    await firstTile.click();

    const viewer = page.getByTestId("image-viewer");
    await expect(viewer).toBeVisible({ timeout: 5_000 });

    // Get the current image URL to verify a different image loads
    const viewerImg = viewer.locator("img, video").first();
    const initialSrc = await viewerImg.getAttribute("src");

    // Click the delete button
    const deleteBtn = viewer.locator('button[title="Delete image"]');
    await deleteBtn.click();

    // Confirm deletion - find the destructive button in the confirmation dialog
    await page.getByRole("button", { name: "Delete", exact: true }).click();

    // Viewer should still be visible (not closed)
    await expect(viewer).toBeVisible({ timeout: 5_000 });

    // The image source should have changed to show a different image
    await expect(viewerImg).not.toHaveAttribute("src", initialSrc!);
  });

  test("deleted image is removed from gallery", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/[1-9]\d* scenes/)).toBeVisible({
      timeout: 15_000,
    });

    // Get initial image count
    const imageCountText = await page.getByText(/\d+ scenes/).textContent();
    const initialCount = parseInt(imageCountText!.match(/\d+/)?.[0] || "0");

    // Open the viewer on the first image
    const firstTile = page.getByTestId("scene-tile").first();
    const imageName = await firstTile.locator("p").first().textContent();
    await firstTile.click();

    const viewer = page.getByTestId("image-viewer");
    await expect(viewer).toBeVisible({ timeout: 5_000 });

    // Delete the image
    const deleteBtn = viewer.locator('button[title="Delete image"]');
    await deleteBtn.click();

    await page.getByRole("button", { name: "Delete", exact: true }).click();

    // Close the viewer to see the gallery
    await page.keyboard.press("Escape");
    await expect(viewer).not.toBeVisible();

    // Wait for the search count to update (gallery refresh after deletion)
    await page.waitForFunction(
      (initialCount) => {
        const countText = document.body.innerText.match(/(\d+)\s+scenes/);
        const newCount = countText ? parseInt(countText[1]) : initialCount;
        return newCount === initialCount - 1;
      },
      initialCount,
      { timeout: 10_000 },
    );
  });
});
