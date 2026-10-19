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

/** The library marker, at the root of both folders (design/library-setup.md §3.2). */
export const LIBRARY_MARKER = 'scene-atlas-library.json'

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
    name === LIBRARY_MARKER ||
    OS_ENTRIES.has(name.toLowerCase())
  )
}

/** Path functions for *platform*, so the helpers here can be tested for any OS. */
export function pathFor(platform: NodeJS.Platform): path.PlatformPath {
  return platform === 'win32' ? path.win32 : path.posix
}

export function isAbsolutePath(
  value: unknown,
  platform: NodeJS.Platform = process.platform,
): value is string {
  return typeof value === 'string' && value.trim() !== '' && pathFor(platform).isAbsolute(value)
}

/**
 * True when *child* is *parent* or a folder inside it. Both should be absolute. Windows
 * and macOS paths compare case-insensitively, as their file systems usually do.
 */
export function isSameOrInside(
  child: string,
  parent: string,
  platform: NodeJS.Platform = process.platform,
): boolean {
  const p = pathFor(platform)
  let c = p.resolve(child)
  let par = p.resolve(parent)
  if (platform === 'win32' || platform === 'darwin') {
    c = c.toLowerCase()
    par = par.toLowerCase()
  }
  const rel = p.relative(par, c)
  return rel === '' || (rel !== '..' && !rel.startsWith('..' + p.sep) && !p.isAbsolute(rel))
}

/** True when both paths name the same folder (see isSameOrInside). */
export function isSamePath(
  a: string,
  b: string,
  platform: NodeJS.Platform = process.platform,
): boolean {
  return isSameOrInside(a, b, platform) && isSameOrInside(b, a, platform)
}

/**
 * True when *dir* holds files or folders Scene Atlas didn't create, e.g. the user's
 * existing map collection, so it must not be deleted. Either storage folder may hold the
 * other's entries (one folder for both is allowed). Stops at the first such entry, so a
 * huge folder is cheap to check.
 */
export function hasForeignEntries(dir: string): boolean {
  let handle: fs.Dir
  try {
    handle = fs.opendirSync(dir)
  } catch (err) {
    // Missing holds nothing; anything else (a file, no access) can't be vouched for.
    return (err as NodeJS.ErrnoException).code !== 'ENOENT'
  }
  try {
    for (let entry = handle.readSync(); entry !== null; entry = handle.readSync()) {
      if (!isOwnEntry(entry.name)) return true
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
    // Unset, empty or relative falls back to the standard location
    const set = env.LOCALAPPDATA
    const localAppData =
      set && path.win32.isAbsolute(set) ? set : path.win32.join(dirs.home, 'AppData', 'Local')
    return path.win32.join(localAppData, 'Scene Atlas')
  }
  return path.join(dirs.documents, 'Scene Atlas')
}

/** Create both storage roots and check they are writable. Never called on the linked
 * folder, which is read-only (design/library-setup.md §1). Returns an error message or null. */
export function prepareStorageDirs(appDataDir: string, imageLibraryDir: string): string | null {
  const dirs: [string, string][] = [
    ['Search data folder', appDataDir],
    ['Imported maps folder', imageLibraryDir],
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
