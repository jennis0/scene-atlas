// The library's three folders as the desktop app handles them (design/library-setup.md):
// validating a choice from the UI, deciding whether it changes anything, and which
// provisional folders it replaces. Node-only (no electron import) so it can be unit
// tested with `node --test`. The backend is authoritative for the library rules; these
// checks only stop Electron from creating or deleting folders it shouldn't.
import * as fs from 'fs'
import * as path from 'path'
import {
  hasForeignEntries,
  isAbsolutePath,
  isSameOrInside,
  isSamePath,
  pathFor,
} from './storageDirs.ts'

export type FolderKind = 'appData' | 'store' | 'linked'

export interface LibraryDirs {
  /** Database, search index, thumbnails, logs (the backend's APP_DATA_DIR) */
  appData: string
  /** Imported originals, backups and the marker (IMAGE_LIBRARY_DIR) */
  store: string
  /** The user's own maps folder: read-only, and may be offline (LINKED_LIBRARY_DIR) */
  linked: string | null
}

/** The two storage folders a new library gets (config.ts getDefaultDirs). */
export type DefaultDirs = Pick<LibraryDirs, 'appData' | 'store'>

export function isFolderKind(value: unknown): value is FolderKind {
  return value === 'appData' || value === 'store' || value === 'linked'
}

function absolute(value: unknown, platform: NodeJS.Platform): string | null {
  return isAbsolutePath(value, platform) ? pathFor(platform).resolve(value) : null
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
    return { error: "The Imported images folder can't be your images folder, or contain it." }
  }
  if (linked && isSameOrInside(linked, appData, platform)) {
    return { error: "The Search data folder can't be your images folder, or contain it." }
  }
  return { dirs: { appData, store, linked } }
}

/** True when *next* names different folders from *current*, compared as isSamePath does. */
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
 * The provisional folders that *next* replaces, to delete once the backend has stopped.
 * Only *defaults* are ever candidates, so a config edited by hand can't name others. A
 * folder that is, contains or sits inside any of the new folders is kept: deleting it
 * would delete part of the new library, or write inside the linked folder.
 */
export function provisionalDirsToDelete(
  current: LibraryDirs,
  next: LibraryDirs,
  defaults: DefaultDirs,
  platform: NodeJS.Platform = process.platform,
): string[] {
  const keep = [next.appData, next.store, next.linked].filter((d): d is string => d !== null)
  const candidates = [current.appData, current.store].filter(
    (dir, i, all) =>
      all.findIndex((other) => isSamePath(other, dir, platform)) === i &&
      (isSamePath(dir, defaults.appData, platform) || isSamePath(dir, defaults.store, platform)),
  )
  return candidates.filter(
    (dir) =>
      !keep.some((k) => isSameOrInside(k, dir, platform) || isSameOrInside(dir, k, platform)),
  )
}

/**
 * Delete the replaced provisional folders (provisionalDirsToDelete), each only if it holds
 * nothing Scene Atlas didn't create, then the "Scene Atlas" folder the defaults sit in if
 * that's left empty. Nothing can have been imported into them: the gallery is gated until
 * setup is complete.
 */
export async function removeProvisionalDirs(dirs: string[], defaults: DefaultDirs): Promise<void> {
  if (dirs.length === 0) return
  for (const dir of dirs) {
    if (hasForeignEntries(dir)) {
      console.log('[electron] Keeping a folder that holds other files:', dir)
      continue
    }
    // Windows can hold the stopped backend's files open for a moment (EBUSY, EPERM).
    await fs.promises
      .rm(dir, { recursive: true, force: true, maxRetries: 4, retryDelay: 200 })
      .catch((err) => console.warn("[electron] Couldn't delete a folder:", dir, err))
  }
  // rmdir fails unless the folder is empty.
  await fs.promises.rmdir(path.dirname(defaults.appData)).catch(() => {})
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
  return inside ? `Your images folder isn't available: ${linked}` : null
}

/** True when *dir* doesn't exist or has nothing in it (a file isn't empty). */
export function isMissingOrEmpty(dir: string): boolean {
  try {
    return fs.readdirSync(dir).length === 0
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === 'ENOENT'
  }
}
