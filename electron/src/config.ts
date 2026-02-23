import { app } from 'electron'
import * as fs from 'fs'
import * as path from 'path'

interface AppConfig {
  dataDir: string
}

function getConfigPath(): string {
  // Small JSON file always in userData (system drive) — just stores the pointer
  return path.join(app.getPath('userData'), 'scene-atlas-config.json')
}

export function loadConfig(): AppConfig | null {
  const configPath = getConfigPath()
  if (!fs.existsSync(configPath)) return null
  try {
    const raw = fs.readFileSync(configPath, 'utf-8')
    const parsed = JSON.parse(raw) as AppConfig
    if (!parsed.dataDir) return null
    return parsed
  } catch {
    return null
  }
}

export function saveConfig(config: AppConfig): void {
  const configPath = getConfigPath()
  fs.mkdirSync(path.dirname(configPath), { recursive: true })
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2))
}

export function getDefaultDataDir(): string {
  // Default to Documents/Scene Atlas — more visible, typically on a larger drive
  // than AppData\Roaming which is almost always on the system C: drive
  return path.join(app.getPath('documents'), 'Scene Atlas', 'data')
}
