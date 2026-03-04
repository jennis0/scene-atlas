import { test, expect } from '../fixtures/base'
import path from 'path'
import fs from 'fs'

test.describe('Import flow', () => {
  test('import dialog opens and shows upload UI', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('h1')).toContainText('Scene Atlas')

    // Click the Import button (has title="Import images")
    await page.getByTitle('Import images').click()

    // The import dialog should open — custom Dialog uses div.fixed.inset-0.z-50
    await expect(page.getByText('Import Scenes')).toBeVisible({ timeout: 5_000 })

    // Should show upload controls
    await expect(
      page.getByText(/Drop files or folders here/),
    ).toBeVisible()
    await expect(
      page.getByText('Browse files'),
    ).toBeVisible()
  })

  test('upload a file and see it in preview', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('h1')).toContainText('Scene Atlas')

    // Open import dialog
    await page.getByTitle('Import images').click()
    await expect(page.getByText('Import Scenes')).toBeVisible({ timeout: 5_000 })

    // Find a test image to upload
    const imageDir =
      process.env.E2E_IMAGE_DIR ||
      path.resolve(__dirname, '..', '.tmp-images')

    // In CI, images must be available — fail hard if missing
    if (!fs.existsSync(imageDir)) {
      if (process.env.CI) throw new Error(`Image dir missing: ${imageDir}`)
      test.skip()
      return
    }

    const testFile = path.resolve(imageDir, 'LooseFile_Tavern.jpg')
    if (!fs.existsSync(testFile)) {
      if (process.env.CI) throw new Error(`Test file missing: ${testFile}`)
      test.skip()
      return
    }

    // Use the file chooser to upload
    const fileChooserPromise = page.waitForEvent('filechooser')

    // Click the "Browse files" button to trigger file chooser
    await page.getByText('Browse files').click()

    const fileChooser = await fileChooserPromise
    await fileChooser.setFiles(testFile)

    // Wait for upload and analysis to complete — auto-confirms and transitions to processing/done
    await expect(
      page.getByText(/Processing\u2026|Import Complete/i),
    ).toBeVisible({ timeout: 30_000 })
  })
})
