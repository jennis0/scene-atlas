// Take the README screenshots from a running demo instance (see design/brand.md, Screenshots).
// Captures at 1x so maps stay thumbnail-sized, crops below the third row of cards, and
// writes PNGs; convert to WebP for docs/public/screenshots/.
//
// Usage: node scripts/demo/screenshots.mjs http://127.0.0.1:8123 <out dir>
import { chromium } from '@playwright/test'

const [server, out] = process.argv.slice(2)
const QUERY = 'snowy mountain pass'

const browser = await chromium.launch()
for (const scheme of ['dark', 'light']) {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    colorScheme: scheme,
    deviceScaleFactor: 1,
  })
  await page.goto(server, { waitUntil: 'networkidle' })
  await page.getByRole('group', { name: 'Image type' }).getByRole('button', { name: /Maps/ }).click()
  await page.getByTitle('Groups').click()
  await page.waitForLoadState('networkidle')
  await page.getByLabel('Search the library').fill(QUERY)
  // The button, not Enter: Enter straight after the view switch is sometimes lost
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await page.getByText('Relevance').first().waitFor() // the sort switches once results arrive
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(2500) // thumbnails fade in
  await page.screenshot({
    path: `${out}/search-${scheme}.png`,
    clip: { x: 0, y: 0, width: 1440, height: 797 },
  })
  await page.close()
}
await browser.close()
