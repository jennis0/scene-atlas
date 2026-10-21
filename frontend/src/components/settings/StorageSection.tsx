/**
 * Settings → Storage locations (desktop app): the three library folders. A change is checked
 * like the wizard's (POST /library/inspect), then applied by the desktop app, which restarts
 * the backend in the window (design/library-setup.md §6).
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { SettingRow } from '@/components/settings/SettingRow'
import { SettingsSection } from '@/components/settings/SettingsSection'
import type { LibraryDirs, LibraryFolderKind } from '@/electron'
import { useLibraryInspect } from '@/hooks/useLibraryInspect'
import { useLibraryStatus } from '@/hooks/useLibraryStatus'
import { useStorageDirs } from '@/hooks/useStorageDirs'
import type { InspectResult } from '@/lib/api/libraryApi'
import { StopUsingFolder } from './StopUsingFolder'

type Pending = Partial<Record<LibraryFolderKind, string>>

interface StoragePathRowProps {
  label: string
  description: string
  current: string | null | undefined
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

/** The folders in use once the pending changes apply; null when nothing is pending */
function proposedDirs(dirs: LibraryDirs | null, pending: Pending): LibraryDirs | null {
  if (!dirs || Object.keys(pending).length === 0) return null
  return {
    appData: pending.appData ?? dirs.appData,
    store: pending.store ?? dirs.store,
    linked: pending.linked ?? dirs.linked,
  }
}

/** What the check says about the proposed folders */
function checkNote(
  checking: boolean,
  result: InspectResult | null,
  currentLibraryId: string | undefined,
): string | null {
  if (checking) return 'Checking the folders…'
  const library = result?.library
  if (library && currentLibraryId !== undefined && library.library_id !== currentLibraryId) {
    return 'Scene Atlas library found.'
  }
  if (result?.store_has_maps) return 'This folder already has images in it.'
  return result?.message ?? null
}

export function StorageSection({ open }: { open: boolean }) {
  const { dirs } = useStorageDirs(open)
  const { data: status } = useLibraryStatus(open)
  const [pending, setPending] = useState<Pending>({})
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)

  const changed = Object.keys(pending).length > 0
  const proposed = proposedDirs(dirs, pending)
  const inspection = useLibraryInspect(proposed)

  const browse = async (kind: LibraryFolderKind) => {
    const current = pending[kind] ?? dirs?.[kind] ?? undefined
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
      if (outcome.error) {
        setApplyError(outcome.error)
        setApplying(false)
      } else if (!outcome.restarted) {
        setPending({})
        setApplying(false)
      }
      // Restarted: the page reloads, so stay busy until it does
    } catch {
      setApplyError("Couldn't change the folders.")
      setApplying(false)
    }
  }

  const cancel = () => {
    setPending({})
    setApplyError(null)
  }

  return (
    <SettingsSection title="Storage locations">
      <StoragePathRow
        label="Search data"
        description="Stores metadata and thumbnails. Best on a fast drive."
        current={dirs?.appData}
        pending={pending.appData}
        onBrowse={() => void browse('appData')}
      />
      <StoragePathRow
        label="Imported images"
        description="Stores full resolution images. It can be stored on any large drive."
        current={dirs?.store}
        pending={pending.store}
        onBrowse={() => void browse('store')}
      />
      <StoragePathRow
        label="Images folder"
        description="Your own folder of images, read where it is."
        current={dirs?.linked}
        pending={pending.linked}
        empty="None"
        browseLabel={dirs?.linked ? 'Change' : 'Choose'}
        onBrowse={() => void browse('linked')}
        extra={dirs?.linked && status?.linked && <StopUsingFolder linked={status.linked} />}
      />

      {changed && (
        <PendingChange
          pending={pending}
          inspection={inspection}
          currentLibraryId={status?.library_id}
          applying={applying}
          applyError={applyError}
          onApply={() => void apply()}
          onCancel={cancel}
        />
      )}
    </SettingsSection>
  )
}

/** The pending folder change: what the check found, and restart to apply it or cancel */
function PendingChange({
  pending,
  inspection: { state: inspect, result, refusal: inspectRefusal },
  currentLibraryId,
  applying,
  applyError,
  onApply,
  onCancel,
}: {
  pending: Pending
  inspection: ReturnType<typeof useLibraryInspect>
  currentLibraryId: string | undefined
  applying: boolean
  applyError: string | null
  onApply: () => void
  onCancel: () => void
}) {
  const movesFiles = pending.appData !== undefined || pending.store !== undefined
  const refusal =
    applyError ??
    inspectRefusal ??
    (inspect.status === 'failed' ? "Couldn't check these folders." : null)
  const note = checkNote(inspect.status === 'checking', result, currentLibraryId)

  return (
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
          onClick={onApply}
          disabled={applying || !result || !!inspectRefusal}
        >
          {applying ? 'Restarting…' : 'Restart now to apply'}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 text-xs"
          onClick={onCancel}
          disabled={applying}
        >
          Cancel
        </Button>
      </div>
    </div>
  )
}
