// The library's three folders as the desktop app handles them (design/library-setup.md):
// validating a choice from the UI, deciding whether it changes anything, and which
// provisional folders it replaces. Node-only (no electron import) so it can be unit
// tested with `node --test`. The backend is authoritative for the library rules; these
// checks only stop Electron from creating or deleting folders it shouldn't.
import * as fs from 'fs'
import * as path from 'path'
import { isSameOrInside, isSamePath } from './storageDirs.ts'

export type FolderKind = 'appData' | 'store' | 'linked'

export interface LibraryDirs {
  /** Database, search index, thumbnails, logs (the backend's APP_DATA_DIR) */
  appData: string
  /** Imported originals, backups and the marker (IMAGE_LIBRARY_DIR) */
  store: string
  /** The user's own maps folder: read-only, and may be offline (LINKED_LIBRARY_DIR) */
  linked: string | null
}

export function isFolderKind(value: unknown): value is FolderKind {
  return value === 'appData' || value === 'store' || value === 'linked'
}

function pathFor(platform: NodeJS.Platform): path.PlatformPath {
  return platform === 'win32' ? path.win32 : path.posix
}

function absolute(value: unknown, platform: NodeJS.Platform): string | null {
  if (typeof value !== 'string' || value.trim() === '') return null
  const p = pathFor(platform)
  return p.isAbsolute(value) ? p.resolve(value) : null
}

/**
 * Check the folders the UI sent (`applyLibrary`) and normalise them. The store and app data
 * may sit inside the linked folder but may not be it or contain it: a library purge
 * deletes the store, so it must never hold the user's maps.
 */
export function parseLibraryDirs(
  raw: unknown,
  platform: NodeJS.Platform = process.platform,
): { dirs: LibraryDirs } | { error: string } {
  const value = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const appData = absolute(value.appData, platform)
  const store = absolute(value.store, platform)
  const linkedRaw = value.linked
  const linked =
    linkedRaw === null || linkedRaw === undefined || linkedRaw === ''
      ? null
      : absolute(linkedRaw, platform)
  if (!appData || !store || (linkedRaw && !linked)) {
    return { error: 'Each folder must be a full path.' }
  }
  if (linked && isSameOrInside(linked, store, platform)) {
    return { error: "The Imported maps folder can't be your maps folder, or contain it." }
  }
  if (linked && isSameOrInside(linked, appData, platform)) {
    return { error: "The Search data folder can't be your maps folder, or contain it." }
  }
  return { dirs: { appData, store, linked } }
}

/** True when *next* names different folders from *current*. */
export function dirsChanged(
  current: LibraryDirs,
  next: LibraryDirs,
  platform: NodeJS.Platform = process.platform,
): boolean {
  const linkedSame =
    current.linked === null || next.linked === null
      ? current.linked === next.linked
      : isSamePath(current.linked, next.linked, platform)
  return (
    !isSamePath(current.appData, next.appData, platform) ||
    !isSamePath(current.store, next.store, platform) ||
    !linkedSame
  )
}

/**
 * The provisional folders (the defaults written on first launch) that *next* replaces, so
 * can be deleted once the backend has stopped. A folder that is, contains or sits inside
 * any of the new folders is kept: deleting it would delete part of the new library, or
 * write inside the linked folder.
 */
export function provisionalDirsToDelete(
  current: LibraryDirs,
  next: LibraryDirs,
  platform: NodeJS.Platform = process.platform,
): string[] {
  const keep = [next.appData, next.store, next.linked].filter((d): d is string => d !== null)
  const candidates = [current.appData, current.store].filter(
    (dir, i, all) => all.findIndex((other) => isSamePath(other, dir, platform)) === i,
  )
  return candidates.filter(
    (dir) =>
      !keep.some((k) => isSameOrInside(k, dir, platform) || isSameOrInside(dir, k, platform)),
  )
}

/**
 * An error when a storage folder sits inside the linked folder and the linked folder is
 * missing (a drive that isn't plugged in). Creating the storage folder would create the
 * linked folder too, on whatever disk now holds that path.
 */
export function unavailableLinkedError(dirs: LibraryDirs): string | null {
  const { linked } = dirs
  if (!linked || fs.existsSync(linked)) return null
  const inside = [dirs.appData, dirs.store].some((dir) => isSameOrInside(dir, linked))
  return inside ? `Your maps folder isn't available: ${linked}` : null
}

/** True when *dir* doesn't exist or has nothing in it. */
export function isMissingOrEmpty(dir: string): boolean {
  try {
    return fs.readdirSync(dir).length === 0
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === 'ENOENT'
  }
}
