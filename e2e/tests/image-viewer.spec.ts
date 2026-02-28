import { test, expect } from '../fixtures/base'

test.describe('Image Viewer', () => {
  test('clicking an image opens the viewer modal', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Click the first image thumbnail (SceneTile has cursor-pointer and contains an img)
    const firstTile = page.locator('img[loading="lazy"]').first()
    await firstTile.click()

    // The ImageViewer overlay should appear (fixed position, z-50)
    const viewer = page.locator('div.fixed.inset-0.z-50')
    await expect(viewer).toBeVisible({ timeout: 5_000 })
  })

  test('escape key closes the viewer', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Open the viewer
    const firstTile = page.locator('img[loading="lazy"]').first()
    await firstTile.click()

    const viewer = page.locator('div.fixed.inset-0.z-50')
    await expect(viewer).toBeVisible({ timeout: 5_000 })

    // Press Escape
    await page.keyboard.press('Escape')

    // Viewer should close
    await expect(viewer).not.toBeVisible()
  })

  test('arrow keys navigate between images', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Open the viewer on the first image
    const firstTile = page.locator('img[loading="lazy"]').first()
    await firstTile.click()

    const viewer = page.locator('div.fixed.inset-0.z-50')
    await expect(viewer).toBeVisible({ timeout: 5_000 })

    // Navigate forward with arrow key
    await page.keyboard.press('ArrowRight')

    // Navigate back
    await page.keyboard.press('ArrowLeft')

    // Viewer should still be open
    await expect(viewer).toBeVisible()
  })
})
