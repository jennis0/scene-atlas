// The desktop app's config (scene-atlas-config.json): its shape, and reading it from
// whatever an older version or a hand edit left on disk. Node-only (no electron import)
// so it can be unit tested with `node --test`; config.ts does the file I/O.
import * as path from 'path'
import {
  sanitizeDisplayPrefs,
  sanitizeWindowColors,
  type DisplayPrefs,
  type WindowColors,
} from './displayPrefs.ts'
import type { LibraryDirs } from './libraryDirs.ts'

export interface AppConfig {
  appDataDir: string
  imageLibraryDir: string
  /** The user's own maps folder, read where it is (design/library-setup.md) */
  linkedLibraryDir?: string
  /** The folders are the defaults written on first launch, not yet confirmed in setup,
   * and were empty then: replacing them in setup deletes them */
  provisional: boolean
  /** The library step of the setup wizard is done, so the wizard resumes after it */
  libraryChosen: boolean
  /** The UI's display choices, so they survive a change of backend port (displayPrefs.ts) */
  displayPrefs?: DisplayPrefs
  /** The UI's last background and text colours, for the window and title bar at launch */
  windowColors?: WindowColors
}

function isAbsolutePath(value: unknown, platform: NodeJS.Platform): value is string {
  const p = platform === 'win32' ? path.win32 : path.posix
  return typeof value === 'string' && value.trim() !== '' && p.isAbsolute(value)
}

/**
 * A usable config from the file's parsed JSON, or null. *migrated* is set when the file
 * should be rewritten in the current shape.
 *
 * A config without `libraryChosen` was written before the setup wizard chose folders, by
 * the storage window, so its folders were chosen. Older configs may also carry
 * convertToWebp or pendingStoredFormat, which are ignored: the stored format is chosen in
 * the setup wizard and kept by the backend (design/first-run.md).
 */
export function parseConfig(
  raw: unknown,
  platform: NodeJS.Platform = process.platform,
): { config: AppConfig; migrated: boolean } | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const parsed = raw as Record<string, unknown>

  // Single-root format: appDataDir ← dataDir, imageLibraryDir ← dataDir/store/images (the
  // existing image root becomes the library root).
  if (typeof parsed.dataDir === 'string' && parsed.dataDir && !parsed.appDataDir) {
    const p = platform === 'win32' ? path.win32 : path.posix
    return {
      config: {
        appDataDir: parsed.dataDir,
        imageLibraryDir: p.join(parsed.dataDir, 'store', 'images'),
        provisional: false,
        libraryChosen: true,
      },
      migrated: true,
    }
  }

  const { appDataDir, imageLibraryDir, linkedLibraryDir } = parsed
  if (typeof appDataDir !== 'string' || !appDataDir) return null
  if (typeof imageLibraryDir !== 'string' || !imageLibraryDir) return null
  const provisional = parsed.provisional === true
  const windowColors = sanitizeWindowColors(parsed.windowColors)
  return {
    config: {
      appDataDir,
      imageLibraryDir,
      ...(isAbsolutePath(linkedLibraryDir, platform) ? { linkedLibraryDir } : {}),
      provisional,
      libraryChosen:
        typeof parsed.libraryChosen === 'boolean' ? parsed.libraryChosen : !provisional,
      displayPrefs: sanitizeDisplayPrefs(parsed.displayPrefs),
      ...(windowColors ? { windowColors } : {}),
    },
    migrated: false,
  }
}

/** The config written on a first launch: the default folders, provisional only when
 * nothing was in them (so deleting them later can't delete anything of the user's). */
export function firstLaunchConfig(
  defaults: { appData: string; store: string },
  defaultsAreEmpty: boolean,
): AppConfig {
  return {
    appDataDir: defaults.appData,
    imageLibraryDir: defaults.store,
    provisional: defaultsAreEmpty,
    libraryChosen: false,
  }
}

export function libraryDirsOf(config: AppConfig): LibraryDirs {
  return {
    appData: config.appDataDir,
    store: config.imageLibraryDir,
    linked: config.linkedLibraryDir ?? null,
  }
}

/** *config* with the folders chosen in setup or Settings: no longer provisional, since
 * the user has now chosen them, even if they kept the defaults. */
export function withChosenLibrary(config: AppConfig, dirs: LibraryDirs): AppConfig {
  const { linkedLibraryDir: _dropped, ...rest } = config
  return {
    ...rest,
    appDataDir: dirs.appData,
    imageLibraryDir: dirs.store,
    ...(dirs.linked ? { linkedLibraryDir: dirs.linked } : {}),
    provisional: false,
    libraryChosen: true,
  }
}
