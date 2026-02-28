import { test as base } from '@playwright/test'
import { execSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { seedTestData } from '../helpers/seed'

const PROJECT_ROOT = path.resolve(__dirname, '..', '..')
const IMAGE_DIR = path.resolve(__dirname, '..', '.tmp-images')

/**
 * Extended test fixture that automatically seeds test data once per worker.
 * Since workers: 1, this seeds exactly once for the entire test run.
 *
 * All test files should import { test, expect } from this module
 * instead of from '@playwright/test'.
 */
export const test = base.extend<object, { seedData: void }>({
  seedData: [
    async ({}, use) => {
      // Generate test images if they don't already exist
      if (!fs.existsSync(IMAGE_DIR) || fs.readdirSync(IMAGE_DIR).length === 0) {
        fs.mkdirSync(IMAGE_DIR, { recursive: true })
        execSync(
          `uv run python scripts/generate_e2e_images.py --output-dir "${IMAGE_DIR}"`,
          { cwd: PROJECT_ROOT, stdio: 'inherit' },
        )
      }

      // Check if data is already seeded (images exist in the backend)
      const checkRes = await fetch('http://localhost:8000/api/v1/search/facets')
      const facets = await checkRes.json()

      if (facets.total_images === 0) {
        // Seed test data via the import API
        await seedTestData(IMAGE_DIR)
      }

      await use()
    },
    { scope: 'worker', auto: true, timeout: 180_000 },
  ],
})

export { expect } from '@playwright/test'
