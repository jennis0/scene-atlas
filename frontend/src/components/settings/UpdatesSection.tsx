import { ExternalLink } from 'lucide-react'
import type { AppUpdateState } from '@/electron'
import type { ServerUpdateStatus } from '@/lib/api/systemApi'
import { SERVER_UPGRADE_DOCS_URL } from '@/lib/constants'
import { SettingRow } from '@/components/settings/SettingRow'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { ToggleSwitch } from '@/components/settings/ToggleSwitch'
import { useAppUpdates } from '@/hooks/useAppUpdates'
import { useServerUpdates } from '@/hooks/useServerUpdates'

function updateStatusText(state: AppUpdateState): string {
  switch (state.status) {
    case 'checking':
      return 'Checking…'
    case 'up-to-date':
      return 'Up to date.'
    case 'downloading':
      return `Downloading version ${state.version} (${state.percent ?? 0}%)`
    case 'ready':
      return `Version ${state.version} is ready. It installs when you quit.`
    case 'available':
      return `Version ${state.version} is out. Install it from the download page.`
    case 'error':
      return state.error ?? "Couldn't check for updates."
    default:
      return 'Not checked yet.'
  }
}

function serverStatusText(state: ServerUpdateStatus): string {
  switch (state.status) {
    case 'available':
      return `Version ${state.latest_version} is out.`
    case 'up_to_date':
      return 'Up to date.'
    case 'disabled':
      return 'Update checks are turned off on this server.'
    case 'unknown':
      return 'Not a release build.'
    default:
      return 'Not checked yet.'
  }
}

const BUTTON =
  'shrink-0 rounded border border-border/50 px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:hover:text-muted-foreground'
const PRIMARY_BUTTON =
  'shrink-0 rounded border border-primary/40 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10'

/** The running version, and the update once one is found: from the desktop app's updater,
 * or on a server from the backend's daily check. */
export function UpdatesSection() {
  const desktop = useAppUpdates()
  const server = useServerUpdates()
  if (desktop.state) return <DesktopUpdates {...desktop} state={desktop.state} />
  if (server) return <ServerUpdates state={server} />
  return null
}

type DesktopUpdatesProps = ReturnType<typeof useAppUpdates> & { state: AppUpdateState }

/** Automatic checks, Check now, and installing or downloading the update. */
function DesktopUpdates({ state, check, setEnabled, install, openDownload }: DesktopUpdatesProps) {
  const status = updateStatusText(state)
  const busy = state.status === 'checking' || state.status === 'downloading'

  return (
    <SettingsSection title="Updates">
      <SettingRow
        label="Check for updates"
        description="Looks for new versions on GitHub while the app is open."
      >
        <ToggleSwitch
          label="Check for updates automatically"
          checked={state.checksEnabled}
          onChange={setEnabled}
        />
      </SettingRow>

      <SettingRow label={`Version ${state.currentVersion}`} description={status}>
        {/* The row's text isn't announced as it changes; this is */}
        <span role="status" className="sr-only">
          {status}
        </span>
        {state.status === 'ready' ? (
          <button type="button" onClick={install} className={PRIMARY_BUTTON}>
            Restart to update
          </button>
        ) : state.status === 'available' ? (
          <button type="button" onClick={openDownload} className={PRIMARY_BUTTON}>
            Download
          </button>
        ) : (
          <button type="button" onClick={check} disabled={busy} className={BUTTON}>
            Check now
          </button>
        )}
      </SettingRow>
    </SettingsSection>
  )
}

/** Read-only: the server's admin upgrades it, and turns checks off with CHECK_FOR_UPDATES. */
function ServerUpdates({ state }: { state: ServerUpdateStatus }) {
  const status = serverStatusText(state)

  return (
    <SettingsSection title="Updates">
      <SettingRow label={`Version ${state.current_version}`} description={status}>
        <span role="status" className="sr-only">
          {status}
        </span>
        {state.update_available && (
          <div className="flex flex-col items-end gap-1.5">
            <a
              href={state.release_url}
              target="_blank"
              rel="noopener noreferrer"
              className={`inline-flex items-center gap-1 ${PRIMARY_BUTTON}`}
            >
              Release notes
              <ExternalLink aria-hidden="true" className="h-3 w-3" />
              <span className="sr-only">(opens on GitHub)</span>
            </a>
            <a
              href={SERVER_UPGRADE_DOCS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
            >
              How to upgrade
              <span className="sr-only">(opens the documentation)</span>
            </a>
          </div>
        )}
      </SettingRow>
    </SettingsSection>
  )
}
