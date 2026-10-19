// Checking for, downloading and installing new versions (design/electron.md#updates).
// The rules (which platforms install, the feed override, the state's shape) are in
// updatePolicy.ts; this wires them to electron-updater.
import { app, shell } from 'electron'
import {
  AppImageUpdater,
  autoUpdater,
  BaseUpdater,
  DebUpdater,
  NsisUpdater,
  type AppUpdater,
  type ProgressInfo,
  type UpdateInfo,
} from 'electron-updater'
import * as fs from 'fs'
import {
  canCheck,
  CHECK_INTERVAL_MS,
  FIRST_CHECK_DELAY_MS,
  parseFeedOverride,
  releasePageUrl,
  updateModeFor,
  wholePercent,
  type UpdateMode,
  type UpdateState,
} from './updatePolicy'

export interface UpdaterOptions {
  enabled: boolean
  logPath: string
  /** Stops the backend before the installer runs, which would otherwise find its files in use. */
  stopBackend: () => Promise<void>
  onChange: (state: UpdateState) => void
}

function fileLogger(logPath: string) {
  const write = (level: string, message: unknown) => {
    try {
      fs.appendFileSync(logPath, `${new Date().toISOString()} ${level} ${String(message)}\n`)
    } catch {
      // Logging must never break updating.
    }
  }
  // No debug: electron-updater's is optional, and its debug output is per-chunk noise.
  return {
    info: (message?: unknown) => {
      write('info', message)
    },
    warn: (message?: unknown) => {
      write('warn', message)
    },
    error: (message?: unknown) => {
      write('error', message)
    },
  }
}

/**
 * The installer-specific updater, chosen here rather than by electron-updater. Its own
 * pick on Linux reads resources/package-type, which the .deb build writes into the unpacked
 * app that the AppImage is also built from; and without that file it falls back to the
 * AppImage updater, which won't even check outside an AppImage. Linux notify mode only
 * checks, so it uses the .deb updater, which checks anywhere and never downloads here.
 */
function createAppUpdater(mode: UpdateMode): AppUpdater {
  if (process.platform === 'win32') return new NsisUpdater()
  if (process.platform === 'linux')
    return mode === 'install' ? new AppImageUpdater() : new DebUpdater()
  return autoUpdater
}

export class Updater {
  private state: UpdateState
  private firstCheck: NodeJS.Timeout | null = null
  private interval: NodeJS.Timeout | null = null
  private readonly log: ReturnType<typeof fileLogger>
  private readonly updater?: AppUpdater

  constructor(private readonly options: UpdaterOptions) {
    this.log = fileLogger(options.logPath)
    const mode = updateModeFor(process.platform, process.env)
    const currentVersion = app.getVersion()
    const checksEnabled = options.enabled
    const updater = app.isPackaged ? createAppUpdater(mode) : null
    // Inactive means a check would quietly do nothing, so say there's nothing to update.
    if (!updater?.isUpdaterActive()) {
      this.state = { status: 'unsupported', mode, currentVersion, checksEnabled }
      return
    }
    this.state = { status: 'idle', mode, currentVersion, checksEnabled }
    this.updater = updater

    updater.logger = this.log
    updater.autoDownload = mode === 'install'
    updater.autoInstallOnAppQuit = mode === 'install'

    const feedOverride = process.env.SCENE_ATLAS_UPDATE_FEED
    const feed = parseFeedOverride(feedOverride)
    if (feed) {
      this.log.info(`Using the update feed ${feed}`)
      updater.setFeedURL({ provider: 'generic', url: feed })
    } else if (feedOverride) {
      this.log.warn(`Ignoring SCENE_ATLAS_UPDATE_FEED (loopback http only): ${feedOverride}`)
    }

    updater.on('checking-for-update', () => {
      this.set({ status: 'checking' })
    })
    updater.on('update-not-available', () => {
      this.set({ status: 'up-to-date' })
    })
    updater.on('update-available', (info: UpdateInfo) => {
      this.set(
        mode === 'install'
          ? { status: 'downloading', version: info.version, percent: 0 }
          : { status: 'available', version: info.version },
      )
    })
    updater.on('download-progress', (progress: ProgressInfo) => {
      this.set({ status: 'downloading', percent: wholePercent(progress.percent) })
    })
    updater.on('update-downloaded', (info: UpdateInfo) => {
      this.set({ status: 'ready', version: info.version, percent: 100 })
    })
    updater.on('error', (err: Error) => {
      this.log.error(err.stack ?? err.message)
      const downloading = this.state.status === 'downloading'
      this.set({
        status: 'error',
        error: downloading ? "Couldn't download the update." : "Couldn't check for updates.",
      })
    })
  }

  getState(): UpdateState {
    return { ...this.state }
  }

  /** Check after a short delay, then every few hours while the app runs. */
  start(): void {
    this.stopTimers()
    if (this.state.status === 'unsupported' || !this.state.checksEnabled) return
    this.firstCheck = setTimeout(() => this.check(), FIRST_CHECK_DELAY_MS)
    this.interval = setInterval(() => this.check(), CHECK_INTERVAL_MS)
  }

  /** Check now, whether or not automatic checks are on. */
  check(): UpdateState {
    if (this.state.status === 'unsupported' || !canCheck(this.state.status)) {
      return this.getState()
    }
    this.updater?.checkForUpdates().catch(() => {
      // Failures also arrive as an 'error' event, which sets the state.
    })
    return this.getState()
  }

  /** Turn automatic checks on or off. An update already found stays on offer. */
  setEnabled(enabled: boolean): UpdateState {
    if (this.state.status === 'unsupported' || enabled === this.state.checksEnabled) {
      return this.getState()
    }
    this.set({ checksEnabled: enabled })
    this.start()
    return enabled ? this.check() : this.getState()
  }

  /**
   * Restart into the downloaded version. The backend is stopped first: the installer starts
   * straight away, before the app's own quit would stop it. If the installer can't start,
   * the app relaunches on the current version so the backend comes back.
   */
  async install(): Promise<void> {
    if (this.state.mode !== 'install' || this.state.status !== 'ready') return
    this.stopTimers()
    await this.options.stopBackend()
    if (this.updater instanceof BaseUpdater && this.updater.install(true, true)) {
      app.quit()
      return
    }
    this.log.error('The installer did not start; relaunching on the current version')
    app.relaunch()
    app.exit(0)
  }

  /** Notify mode: open the new version's release page in the browser. */
  openDownload(): void {
    void shell.openExternal(releasePageUrl(this.state.version))
  }

  private set(patch: Partial<UpdateState>): void {
    this.state = { ...this.state, ...patch }
    if (this.state.status !== 'error') delete this.state.error
    this.options.onChange(this.getState())
  }

  private stopTimers(): void {
    if (this.firstCheck) clearTimeout(this.firstCheck)
    if (this.interval) clearInterval(this.interval)
    this.firstCheck = null
    this.interval = null
  }
}
