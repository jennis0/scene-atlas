import type { AppUpdateState } from '@/electron'
import { SettingRow } from '@/components/settings/SettingRow'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { ToggleSwitch } from '@/components/settings/ToggleSwitch'
import { useAppUpdates } from '@/hooks/useAppUpdates'

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

const BUTTON =
  'shrink-0 rounded border border-border/50 px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:hover:text-muted-foreground'
const PRIMARY_BUTTON =
  'shrink-0 rounded border border-primary/40 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10'

/** Desktop only: the version, automatic checks, and the update once one is found. */
export function UpdatesSection() {
  const { state, check, setEnabled, install, openDownload } = useAppUpdates()
  if (!state) return null
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
