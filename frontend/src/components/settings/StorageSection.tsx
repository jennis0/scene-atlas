/**
 * Settings → Storage locations (desktop app): the three library folders. A change is checked
 * like the wizard's (POST /library/inspect), then applied by the desktop app, which restarts
 * the backend in the window (design/library-setup.md §6).
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { SettingRow } from '@/components/settings/SettingRow'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { useLibraryInspect } from '@/hooks/useLibraryInspect'
import { useLibraryStatus } from '@/hooks/useLibraryStatus'
import { useStorageDirs } from '@/hooks/useStorageDirs'
import type { InspectRequest } from '@/lib/api/libraryApi'
import { StopUsingFolder } from './StopUsingFolder'

type FolderKind = 'appData' | 'store' | 'linked'
type Pending = Partial<Record<FolderKind, string>>

interface StoragePathRowProps {
  label: string
  description: string
  current: string | null
  pending: string | undefined
  /** Shown when there's no folder */
  empty?: string
  browseLabel?: string
  onBrowse: () => void
  extra?: React.ReactNode
}

function StoragePathRow({
  label,
  description,
  current,
  pending,
  empty = '—',
  browseLabel = 'Change',
  onBrowse,
  extra,
}: StoragePathRowProps) {
  const display = pending ?? current ?? empty
  return (
    <SettingRow label={label} description={description} requiresRestart>
      <div className="flex flex-col items-end gap-1.5">
        <span
          className={`max-w-[10.59rem] truncate text-xs font-mono ${pending ? 'text-primary' : 'text-muted-foreground'}`}
          title={display}
        >
          {display}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onBrowse}
            aria-label={`${browseLabel} ${label.toLowerCase().replace(/ folder$/, '')} folder`}
            className="shrink-0 rounded border border-border/50 px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {browseLabel}
          </button>
          {extra}
        </div>
      </div>
    </SettingRow>
  )
}

export function StorageSection({ open }: { open: boolean }) {
  const { dirs } = useStorageDirs(open)
  const { data: status } = useLibraryStatus(open)
  const [pending, setPending] = useState<Pending>({})
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)

  const changed = Object.keys(pending).length > 0
  const proposed = dirs && {
    appData: pending.appData ?? dirs.appData,
    store: pending.store ?? dirs.store,
    linked: pending.linked ?? dirs.linked,
  }
  // Checked only when something changed; the hook keys requests by content
  const request: InspectRequest | null =
    changed && proposed
      ? {
          app_data: proposed.appData,
          store: proposed.store,
          ...(proposed.linked && { linked: proposed.linked }),
        }
      : null
  const { state: inspect } = useLibraryInspect(request)
  const result = inspect.status === 'done' ? inspect.result : null

  const browse = async (kind: FolderKind) => {
    const current = pending[kind] ?? (dirs ? (dirs[kind] ?? undefined) : undefined)
    const chosen = await window.electronAPI?.chooseFolder(kind, current)
    if (!chosen) return
    setApplyError(null)
    setPending((p) => {
      const next = { ...p }
      if (dirs && chosen === dirs[kind]) delete next[kind]
      else next[kind] = chosen
      return next
    })
  }

  const apply = async () => {
    const api = window.electronAPI
    if (!api || !proposed) return
    setApplying(true)
    setApplyError(null)
    try {
      const outcome = await api.applyLibrary(proposed)
      // Restarted: the page reloads. Otherwise nothing changed, or it couldn't be applied.
      if (outcome.error) setApplyError(outcome.error)
      else if (!outcome.restarted) setPending({})
      if (outcome.error || !outcome.restarted) setApplying(false)
    } catch {
      setApplyError("Couldn't change the folders.")
      setApplying(false)
    }
  }

  const movesFiles = pending.appData !== undefined || pending.store !== undefined
  const refusal =
    applyError ??
    (result?.outcome === 'error' ? (result.message ?? "Couldn't use these folders.") : null) ??
    (inspect.status === 'failed' ? "Couldn't check these folders." : null)
  const note =
    inspect.status === 'checking'
      ? 'Checking the folders…'
      : result?.library && status && result.library.library_id !== status.library_id
        ? 'Scene Atlas library found.'
        : result?.store_has_maps
          ? 'This folder already has maps in it.'
          : (result?.message ?? null)

  return (
    <SettingsSection title="Storage locations">
      <StoragePathRow
        label="Search data"
        description="Metadata, thumbnails and the search index. Best on a fast drive."
        current={dirs?.appData ?? null}
        pending={pending.appData}
        onBrowse={() => void browse('appData')}
      />
      <StoragePathRow
        label="Imported maps"
        description="Full resolution copies of the maps you import, and backups. Any large drive works."
        current={dirs?.store ?? null}
        pending={pending.store}
        onBrowse={() => void browse('store')}
      />
      <StoragePathRow
        label="Maps folder"
        description="Your own folder of maps, read where it is."
        current={dirs?.linked ?? null}
        pending={pending.linked}
        empty="None"
        browseLabel={dirs?.linked ? 'Change' : 'Choose'}
        onBrowse={() => void browse('linked')}
        extra={dirs?.linked && status?.linked && <StopUsingFolder linked={status.linked} />}
      />

      {changed && (
        <div className="space-y-2 rounded border border-warning/30 bg-warning/5 p-3">
          {movesFiles && (
            <p className="text-xs text-muted-foreground">
              Changing a folder doesn&apos;t move your files. Move them yourself before restarting.
            </p>
          )}
          <p role="status" className="text-xs text-muted-foreground">
            {note}
          </p>
          {refusal && (
            <p role="alert" className="text-xs text-destructive">
              {refusal}
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              className="h-7 text-xs"
              onClick={() => void apply()}
              disabled={applying || !result || result.outcome === 'error'}
            >
              {applying ? 'Restarting…' : 'Restart now to apply'}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => {
                setPending({})
                setApplyError(null)
              }}
              disabled={applying}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </SettingsSection>
  )
}
