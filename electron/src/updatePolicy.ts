// What the desktop app's updater does on each platform, and the state it reports to the
// UI (design/electron.md#updates). Node-only (no electron import) so it can be unit tested
// with `node --test`.

/** What this install can do: 'install' downloads and installs a new version; 'notify' only
 * says one is out and links to its download. */
export type UpdateMode = 'install' | 'notify'

/**
 * The user's choice, in Settings or the setup wizard:
 * - automatic: check, download in the background, install on restart or quit
 * - ask: check and say a version is out; download and install only when the user asks
 * - off: no checks of its own; Check now still works, and then behaves like ask
 */
export type UpdateChoice = 'automatic' | 'ask' | 'off'

const UPDATE_CHOICES: readonly UpdateChoice[] = ['automatic', 'ask', 'off']

/** Until the user chooses, nothing checks; once setup is done, this is chosen for them. */
export const DEFAULT_UPDATE_CHOICE: UpdateChoice = 'ask'

export type UpdateStatus =
  | 'unsupported' // dev build: there is nothing to update
  | 'idle' // not checked yet this session
  | 'checking'
  | 'up-to-date'
  | 'available' // notify mode: a newer version is out
  | 'downloading' // install mode: fetching the newer version
  | 'ready' // install mode: downloaded, installs on restart or quit
  | 'error'

export interface UpdateState {
  status: UpdateStatus
  mode: UpdateMode
  currentVersion: string
  /** The user's choice, or the default while they haven't made one */
  choice: UpdateChoice
  /** False until the user (or the end of setup) has chosen: no automatic checks until then */
  choiceMade: boolean
  /** The newer version, once one is found */
  version?: string
  /** 0–100 while downloading */
  percent?: number
  /** A short message for the UI when status is 'error' */
  error?: string
}

/** Checked a little after launch, so the check doesn't compete with the backend's start. */
export const FIRST_CHECK_DELAY_MS = 15_000
export const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000

const RELEASES_URL = 'https://github.com/jennis0/scene-atlas/releases'
// A version is "1.2.3" or "1.2.3-beta.1": a release, then an optional prerelease after
// the first hyphen. Two simple patterns rather than one with a nested optional group.
const RELEASE = /^\d+\.\d+\.\d+$/
const PRERELEASE = /^[0-9A-Za-z.-]+$/

function isPlainVersion(version: string): boolean {
  const hyphen = version.indexOf('-')
  if (hyphen === -1) return RELEASE.test(version)
  return RELEASE.test(version.slice(0, hyphen)) && PRERELEASE.test(version.slice(hyphen + 1))
}

/**
 * Installing needs an install the app can replace itself: the NSIS install on Windows and
 * the AppImage on Linux (APPIMAGE is set when it runs from one). macOS can't install until
 * builds are signed (Squirrel.Mac checks the signature), and a .deb belongs to the package
 * manager, so both only notify.
 */
export function updateModeFor(
  platform: NodeJS.Platform,
  env: Readonly<Record<string, string | undefined>>,
): UpdateMode {
  if (platform === 'win32') return 'install'
  if (platform === 'linux' && env.APPIMAGE) return 'install'
  return 'notify'
}

/**
 * The update feed the packaged-app tests point the app at (SCENE_ATLAS_UPDATE_FEED), or
 * null to use the GitHub releases in app-update.yml. Only plain http on the loopback
 * address is accepted, so the variable can't redirect updates to another machine.
 */
export function parseFeedOverride(raw: string | undefined): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') return null
    if (url.username || url.password) return null
    return url.href
  } catch {
    return null
  }
}

/** The release page to download *version* from; the releases list for anything that isn't
 * a plain version, so text from the feed never ends up in the URL. */
export function releasePageUrl(version: string | undefined): string {
  return version && isPlainVersion(version) ? `${RELEASES_URL}/tag/v${version}` : RELEASES_URL
}

export function parseUpdateChoice(raw: unknown): UpdateChoice | null {
  return UPDATE_CHOICES.find((choice) => choice === raw) ?? null
}

/**
 * The choice a saved config records, or null if none was made. Configs from 0.1.x have
 * `checkForUpdates: false` when checks were turned off, and nothing otherwise: that wasn't
 * a choice about installing, so only the off is kept.
 */
export function savedUpdateChoice(config: {
  updateChoice?: unknown
  checkForUpdates?: unknown
}): UpdateChoice | null {
  return parseUpdateChoice(config.updateChoice) ?? (config.checkForUpdates === false ? 'off' : null)
}

export interface UpdaterBehaviour {
  /** Checks shortly after launch and every few hours */
  checksAutomatically: boolean
  /** A version found is downloaded without asking */
  downloadsAutomatically: boolean
  /** A downloaded version is installed when the app quits */
  installsOnQuit: boolean
}

/**
 * What the updater does by itself for *choice* (null: not made yet) on an install that
 * can *mode*. Nothing installs unless the choice is automatic or the user asked for this
 * update (`requested`, from Update in ask or off). A notify-only install treats automatic
 * as ask: it has nothing to install.
 */
export function updaterBehaviour(
  choice: UpdateChoice | null,
  mode: UpdateMode,
  requested = false,
): UpdaterBehaviour {
  const automatic = choice === 'automatic' && mode === 'install'
  return {
    checksAutomatically: choice === 'automatic' || choice === 'ask',
    downloadsAutomatically: automatic,
    installsOnQuit: mode === 'install' && (automatic || requested),
  }
}

/** Whether a check may start now: not while one is running, nor once an update is found. */
export function canCheck(status: UpdateStatus): boolean {
  return status === 'idle' || status === 'up-to-date' || status === 'error'
}

/** The download's progress as a whole percentage, clamped to 0–100. */
export function wholePercent(raw: unknown): number {
  const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
  return Math.min(100, Math.max(0, Math.floor(value)))
}
