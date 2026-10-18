// Fails the build if a font was inlined into the CSS as a data: URL. The CSP in
// index.html allows fonts from 'self' only, so an inlined font is silently blocked in
// the browser. vite.config.ts keeps fonts out of assetsInlineLimit; this guards it.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const assets = join(import.meta.dirname, '..', 'dist', 'assets')
const offenders = readdirSync(assets)
  .filter((name) => name.endsWith('.css'))
  .filter((name) =>
    /url\(\s*["']?data:(font|application\/(x-)?font)/i.test(
      readFileSync(join(assets, name), 'utf8'),
    ),
  )

if (offenders.length > 0) {
  console.error(
    `Inlined data: fonts in ${offenders.join(', ')}; the CSP blocks them (see vite.config.ts).`,
  )
  process.exit(1)
}
