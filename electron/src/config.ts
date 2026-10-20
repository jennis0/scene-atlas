import { app } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import {
  sanitizeDisplayPrefs,
  sanitizeWindowColors,
  type DisplayPrefs,
  type WindowColors,
} from './displayPrefs'
import { defaultStorageBase } from './storageDirs'
import { savedUpdateChoice, type UpdateChoice } from './updatePolicy'
import { sanitizeWindowState, type WindowState } from './windowState'

interface AppConfig {
  appDataDir: string
  imageLibraryDir: string
  /** The UI's display choices, so they survive a change of backend port (displayPrefs.ts) */
  displayPrefs?: DisplayPrefs
  /** The UI's last background and text colours, for the window and title bar at launch */
  windowColors?: WindowColors
  /** The main window's last size, position and maximised state (windowState.ts) */
  windowState?: WindowState
  /** How the app updates itself (updatePolicy.ts); absent until the user chooses */
  updateChoice?: UpdateChoice
}

/** Legacy config shape written by older versions. */
interface LegacyConfig {
  dataDir?: string
}

function getConfigPath(): string {
  return path.join(app.getPath('userData'), 'scene-atlas-config.json')
}

/** Migrate a legacy single-root config to the two-root schema.
 *
 * appDataDir      ← dataDir           (unchanged; fast data already lives here)
 * imageLibraryDir ← dataDir/store/images  (existing image root becomes new library root)
 */
function migrateLegacyConfig(legacy: LegacyConfig): AppConfig {
  const dataDir = legacy.dataDir!
  return {
    appDataDir: dataDir,
    imageLibraryDir: path.join(dataDir, 'store', 'images'),
  }
}

export function loadConfig(): AppConfig | null {
  const configPath = getConfigPath()
  if (!fs.existsSync(configPath)) return null
  try {
    const raw = fs.readFileSync(configPath, 'utf-8')
    const parsed = JSON.parse(raw) as AppConfig & LegacyConfig

    if (parsed.dataDir && !parsed.appDataDir) {
      const migrated = migrateLegacyConfig(parsed)
      saveConfig(migrated)
      return migrated
    }

    if (!parsed.appDataDir || !parsed.imageLibraryDir) return null
    // Older configs may also carry convertToWebp or pendingStoredFormat: the stored format
    // is now chosen in the setup wizard and kept by the backend (design/first-run.md).
    const windowColors = sanitizeWindowColors(parsed.windowColors)
    const windowState = sanitizeWindowState(parsed.windowState)
    // 0.1.x saved checkForUpdates instead; it is dropped the next time the config is saved.
    const updateChoice = savedUpdateChoice(parsed)
    return {
      appDataDir: parsed.appDataDir,
      imageLibraryDir: parsed.imageLibraryDir,
      displayPrefs: sanitizeDisplayPrefs(parsed.displayPrefs),
      ...(windowColors ? { windowColors } : {}),
      ...(windowState ? { windowState } : {}),
      ...(updateChoice ? { updateChoice } : {}),
    }
  } catch {
    return null
  }
}

export function saveConfig(config: AppConfig): void {
  const configPath = getConfigPath()
  fs.mkdirSync(path.dirname(configPath), { recursive: true })
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2))
}

/** Merge *patch* into the saved config. No-op before setup has saved one. */
export function updateConfig(patch: Partial<AppConfig>): void {
  const config = loadConfig()
  if (config) saveConfig({ ...config, ...patch })
}

export function getDefaultDirs(): { appDataDir: string; imageLibraryDir: string } {
  const base = defaultStorageBase(process.platform, process.env, {
    home: app.getPath('home'),
    documents: app.getPath('documents'),
  })
  return {
    appDataDir: path.join(base, 'data'),
    imageLibraryDir: path.join(base, 'images'),
  }
}
