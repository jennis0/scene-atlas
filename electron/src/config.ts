import { app } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import { parseConfig, type AppConfig } from './appConfig'
import type { DefaultDirs } from './libraryDirs'
import { defaultStorageBase } from './storageDirs'

function getConfigPath(): string {
  return path.join(app.getPath('userData'), 'scene-atlas-config.json')
}

export function loadConfig(): AppConfig | null {
  const configPath = getConfigPath()
  if (!fs.existsSync(configPath)) return null
  try {
    const result = parseConfig(JSON.parse(fs.readFileSync(configPath, 'utf-8')))
    if (!result) return null
    if (result.migrated) saveConfig(result.config)
    return result.config
  } catch {
    return null
  }
}

/**
 * Move a config file that exists but can't be used out of the way, so a first-launch
 * config can replace it without losing it. Returns where it went, or null.
 */
export function setAsideUnusableConfig(): string | null {
  const configPath = getConfigPath()
  if (!fs.existsSync(configPath)) return null
  const aside = `${configPath}.unusable-${Date.now()}`
  try {
    fs.renameSync(configPath, aside)
    return aside
  } catch {
    return null
  }
}

export function saveConfig(config: AppConfig): void {
  const configPath = getConfigPath()
  fs.mkdirSync(path.dirname(configPath), { recursive: true })
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2))
}

/** Merge *patch* into the saved config. No-op before one has been saved. */
export function updateConfig(patch: Partial<AppConfig>): void {
  const config = loadConfig()
  if (config) saveConfig({ ...config, ...patch })
}

/** Where a new library goes: `<base>/data` and `<base>/images` (defaultStorageBase). */
export function getDefaultDirs(): DefaultDirs {
  const base = defaultStorageBase(process.platform, process.env, {
    home: app.getPath('home'),
    documents: app.getPath('documents'),
  })
  return {
    appData: path.join(base, 'data'),
    store: path.join(base, 'images'),
  }
}
