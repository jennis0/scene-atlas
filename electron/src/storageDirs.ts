// Checks on the two storage folders. Node-only (no electron import) so it can be
// unit tested with `node --test`.
import * as fs from 'fs'
import * as path from 'path'

/** What the backend creates in the app data folder (design/storage.md). */
const APP_DATA_ENTRIES = new Set([
  'battlemap.db',
  'battlemap.db-wal',
  'battlemap.db-shm',
  'battlemap.db-journal',
  'config',
  'images', // the server's default library location, inside the app data folder
  'lancedb',
  'logs',
  'models',
  'scheduler',
  'staging',
  'store',
])

/** What the backend creates in the image library folder, besides <xx>/<yy>/ shards. */
const IMAGE_LIBRARY_ENTRIES = new Set(['backups'])

/** OS clutter that doesn't make a folder "someone else's". */
const OS_ENTRIES = new Set([
  'desktop.ini',
  'thumbs.db',
  '$recycle.bin',
  'system volume information',
])

const SHARD_DIR = /^[0-9a-f]{2}$/

function isOwnEntry(name: string): boolean {
  return (
    name.startsWith('.') ||
    SHARD_DIR.test(name) ||
    APP_DATA_ENTRIES.has(name) ||
    IMAGE_LIBRARY_ENTRIES.has(name) ||
    OS_ENTRIES.has(name.toLowerCase())
  )
}

function isSameOrInside(child: string, parent: string): boolean {
  const rel = path.relative(parent, child)
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))
}

/**
 * True when *dir* holds files or folders Scene Atlas didn't create, e.g. the user's
 * existing map collection. Either storage folder may hold the other's entries (one
 * folder for both is allowed), and *otherRoot* or a folder containing it is expected.
 * Stops at the first such entry, so a huge folder is cheap to check.
 */
export function hasForeignEntries(dir: string, otherRoot?: string): boolean {
  let handle: fs.Dir
  try {
    handle = fs.opendirSync(dir)
  } catch {
    return false // missing or unreadable: prepareStorageDirs reports it
  }
  try {
    for (let entry = handle.readSync(); entry !== null; entry = handle.readSync()) {
      if (isOwnEntry(entry.name)) continue
      if (otherRoot && isSameOrInside(otherRoot, path.join(dir, entry.name))) continue
      return true
    }
    return false
  } finally {
    handle.closeSync()
  }
}

/**
 * Where the two storage folders go by default: `<base>/data` and `<base>/images`.
 *
 * On Windows, %LOCALAPPDATA%\Scene Atlas: Documents is often redirected into OneDrive,
 * which would sync the database, search index and thumbnails while they are open (lock
 * conflicts, Files On-Demand evicting them) and every library image. Local AppData is
 * never synced or roamed. Elsewhere, ~/Documents/Scene Atlas.
 */
export function defaultStorageBase(
  platform: NodeJS.Platform,
  env: Record<string, string | undefined>,
  dirs: { home: string; documents: string },
): string {
  if (platform === 'win32') {
    const localAppData = env.LOCALAPPDATA || path.win32.join(dirs.home, 'AppData', 'Local')
    return path.win32.join(localAppData, 'Scene Atlas')
  }
  return path.join(dirs.documents, 'Scene Atlas')
}

/** Create both storage roots and check they are writable. Returns an error message or null. */
export function prepareStorageDirs(appDataDir: string, imageLibraryDir: string): string | null {
  const dirs: [string, string][] = [
    ['App data folder', appDataDir],
    ['Image library folder', imageLibraryDir],
  ]
  for (const [label, dir] of dirs) {
    try {
      fs.mkdirSync(dir, { recursive: true })
      const testFile = path.join(dir, `.write-test-${Date.now()}`)
      fs.writeFileSync(testFile, 'test')
      fs.unlinkSync(testFile)
    } catch (err) {
      return `${label} can't be used: ${dir}\n${(err as Error).message}`
    }
  }
  return null
}
