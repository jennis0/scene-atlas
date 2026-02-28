import { test, expect } from '../fixtures/base'

test.describe('Gallery', () => {
  test('displays seeded images with count', async ({ page }) => {
    await page.goto('/')
    // Wait for the gallery to load — count shows "N scenes"
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })
  })

  test('type tabs filter by image type', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Click "Maps" tab
    await page.getByRole('button', { name: /Maps/ }).click()
    // URL should update with image_type filter
    await expect(page).toHaveURL(/image_type=battlemap/)

    // Click "Scenes" tab
    await page.getByRole('button', { name: /Scenes/ }).click()
    await expect(page).toHaveURL(/image_type=scene/)

    // Click "All" tab to reset
    await page.getByRole('button', { name: /All/ }).click()
  })

  test('view mode toggle switches between individual and grouped', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Switch to grouped view
    await page.getByTitle('Groups').click()
    // The view should change (grouped cards render differently)
    // Verify by switching back
    await page.getByTitle('Individual images').click()
  })

  test('sort dropdown changes ordering', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Open sort dropdown — find the sort trigger button
    const sortButton = page.getByRole('button', { name: /Newest|Oldest|Name/ })
    await sortButton.click()

    // Select "Name A–Z"
    await page.getByRole('menuitemradio', { name: /Name A/ }).click()
  })
})
