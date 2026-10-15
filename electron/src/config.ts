import { app } from 'electron'
import * as fs from 'fs'
import * as path from 'path'

interface AppConfig {
  appDataDir: string
  imageLibraryDir: string
  convertToWebp: boolean
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
    convertToWebp: false,
  }
}

export function loadConfig(): AppConfig | null {
  const configPath = getConfigPath()
  if (!fs.existsSync(configPath)) return null
  try {
    const raw = fs.readFileSync(configPath, 'utf-8')
    const parsed = JSON.parse(raw) as AppConfig & LegacyConfig

    // Migration: old config has dataDir but not appDataDir
    if (parsed.dataDir && !parsed.appDataDir) {
      const migrated = migrateLegacyConfig(parsed)
      saveConfig(migrated)  // Persist migrated config (removes dataDir key)
      return migrated
    }

    if (!parsed.appDataDir || !parsed.imageLibraryDir) return null
    return {
      appDataDir: parsed.appDataDir,
      imageLibraryDir: parsed.imageLibraryDir,
      convertToWebp: parsed.convertToWebp ?? false,
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

export function getDefaultDirs(): { appDataDir: string; imageLibraryDir: string } {
  const base = path.join(app.getPath('documents'), 'Scene Atlas')
  return {
    appDataDir: path.join(base, 'data'),
    imageLibraryDir: path.join(base, 'images'),
  }
}
