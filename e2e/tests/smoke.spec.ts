import { test, expect } from "../fixtures/base";

test.describe("Smoke tests", () => {
  test("backend health check responds", async ({ request }) => {
    const response = await request.get("http://localhost:8000/health");
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    // Status may be "degraded" while CLIP loads in background — that's expected
    expect(["healthy", "degraded"]).toContain(body.status);
  });

  test("frontend loads and shows Scene Atlas title", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("Scene Atlas");
  });

  test("gallery displays seeded images", async ({ page }) => {
    await page.goto("/");
    // Wait for images to load — count should show "N scenes"
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 });
  });
});
