import { test, expect } from '../fixtures/base'

test.describe('Search', () => {
  test('text search filters results and updates URL', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Type a search query matching seeded group name
    const searchInput = page.getByPlaceholder(/Search/)
    await searchInput.fill('ForestClearing')
    await page.getByRole('button', { name: 'Search' }).click()

    // Should show results and URL should contain query
    await expect(page.getByText(/result/)).toBeVisible({ timeout: 10_000 })
    await expect(page).toHaveURL(/q=ForestClearing/)
  })

  test('clearing search restores full gallery', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Search for something
    const searchInput = page.getByPlaceholder(/Search/)
    await searchInput.fill('Cave')
    await page.getByRole('button', { name: 'Search' }).click()
    await expect(page.getByText(/result/)).toBeVisible({ timeout: 10_000 })

    // Clear the search
    await searchInput.clear()
    await page.getByRole('button', { name: 'Search' }).click()

    // Should show all scenes again
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 10_000 })
  })

  test('semantic search prefix shows relevance controls', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText(/\d+ scenes/)).toBeVisible({ timeout: 15_000 })

    // Use ~ prefix for semantic search
    const searchInput = page.getByPlaceholder(/Search/)
    await searchInput.fill('~dark cave with water')
    await page.getByRole('button', { name: 'Search' }).click()

    // The relevance slider should appear (indicates semantic mode was activated)
    // Use .first() because "Relevance" appears in both the sort dropdown and the slider label
    await expect(page.getByText('Relevance').first()).toBeVisible({ timeout: 15_000 })
  })
})
