/**
 * The Library tab's linked folder: its state, "Check for changes" and how often that runs,
 * removing maps whose files are gone, and the way out (design/library-setup.md §4.7).
 * Shown in both modes; the path only in the desktop app.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { plural } from '@/components/imports/format'
import { SegmentedControl } from '@/components/settings/SegmentedControl'
import { useLibraryStatus } from '@/hooks/useLibraryStatus'
import { libraryApi, type LibraryStatus } from '@/lib/api/libraryApi'
import { settingsApi } from '@/lib/api/settingsApi'
import { isApp } from '@/lib/appMode'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { getImportManager } from '@/lib/import/ImportManager'
import { QUERY_KEYS, invalidateGalleryQueries } from '@/lib/queryKeys'
import { RemoveDetachedMaps, StopUsingFolder } from './StopUsingFolder'

type Linked = NonNullable<LibraryStatus['linked']>

/** linked_rescan_minutes (design/library-setup.md §4.3) */
const RESCAN_OPTIONS = [
  { value: 5, label: '5 min', title: 'Every 5 minutes' },
  { value: 15, label: '15 min', title: 'Every 15 minutes' },
  { value: 60, label: 'Hourly', title: 'Every hour' },
  { value: 0, label: 'At startup', title: 'Only when the app starts' },
] as const

export function LinkedFolderSection({ open }: { open: boolean }) {
  const { data: status } = useLibraryStatus(open)
  const linked = status?.linked
  if (!linked) return null
  return (
    <>
      <div className="border-t border-border/50" />
      <section aria-labelledby="linked-folder-title" className="space-y-3">
        <p id="linked-folder-title" className="section-label">
          Maps folder
        </p>
        <FolderState linked={linked} />
        {linked.state !== 'detached' && <RescanControls linked={linked} />}
        {linked.state !== 'detached' && linked.missing_count > 0 && (
          <RemoveMissing linked={linked} />
        )}
        {linked.state === 'detached' ? (
          <ActionRow title="Remove its maps" detail="Its maps can't be opened.">
            <RemoveDetachedMaps linked={linked} />
          </ActionRow>
        ) : (
          isApp && (
            <ActionRow
              title="Stop using this folder"
              detail="Removes its maps from your library. The files stay."
            >
              <StopUsingFolder linked={linked} />
            </ActionRow>
          )
        )}
      </section>
    </>
  )
}

function stateText(linked: Linked): string {
  if (linked.scanning) return 'Checking for changes…'
  switch (linked.state) {
    case 'offline':
      return `${linked.name} isn't available. Reconnect it, then check for changes.`
    case 'detached':
      return 'This folder is no longer used.'
    default:
      return linked.last_scan_at
        ? `${plural(linked.image_count, 'map')}. Last checked ${new Date(
            linked.last_scan_at,
          ).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}.`
        : plural(linked.image_count, 'map')
  }
}

function FolderState({ linked }: { linked: Linked }) {
  return (
    <div className="space-y-0.5">
      <p className="text-sm font-medium text-foreground">{linked.name}</p>
      {isApp && linked.path && (
        <p className="text-xs font-mono text-muted-foreground break-all">{linked.path}</p>
      )}
      <p
        role="status"
        className={`text-xs ${linked.state === 'online' ? 'text-muted-foreground' : 'text-warning'}`}
      >
        {stateText(linked)}
      </p>
    </div>
  )
}

function RescanControls({ linked }: { linked: Linked }) {
  const queryClient = useQueryClient()
  const { data: settings } = useQuery({
    queryKey: QUERY_KEYS.appSettings,
    queryFn: () => settingsApi.get(),
  })

  const scan = useMutation({
    mutationFn: () => libraryApi.scan('manual'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.libraryStatus })
      void getImportManager().refresh()
    },
    onError: (err) => toast.error(getApiErrorMessage(err, "Couldn't check for changes.")),
  })

  const interval = useMutation({
    mutationFn: (minutes: number) => settingsApi.patch({ linked_rescan_minutes: minutes }),
    onSuccess: (saved) => queryClient.setQueryData(QUERY_KEYS.appSettings, saved),
    onError: (err) => toast.error(getApiErrorMessage(err, "Couldn't save how often to check.")),
  })

  const minutes = interval.isPending
    ? interval.variables
    : (settings?.linked_rescan_minutes ?? undefined)
  const checking = linked.scanning || scan.isPending

  return (
    <div className="space-y-2">
      <Button
        size="sm"
        variant="outline"
        className="h-8 gap-1.5"
        onClick={() => scan.mutate()}
        disabled={checking}
      >
        {checking ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" />
        )}
        Check for changes
      </Button>
      {minutes !== undefined && (
        <div className="space-y-1.5">
          <p aria-hidden="true" className="text-xs text-muted-foreground">
            How often to check
          </p>
          <SegmentedControl
            options={RESCAN_OPTIONS}
            value={minutes}
            onChange={(value) => interval.mutate(value)}
            label="How often to check"
          />
        </div>
      )}
    </div>
  )
}

function RemoveMissing({ linked }: { linked: Linked }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const remove = useMutation({
    mutationFn: libraryApi.removeMissing,
    onSuccess: ({ removed }) => {
      setConfirming(false)
      toast.success(`${plural(removed, 'map')} removed.`)
      invalidateGalleryQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.libraryStatus })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.systemInfo })
    },
    onError: (err) => {
      setConfirming(false)
      toast.error(getApiErrorMessage(err, "Couldn't remove the missing maps."))
    },
  })

  const count = plural(linked.missing_count, 'map')
  return (
    <ActionRow
      title={`${count} ${linked.missing_count === 1 ? 'is' : 'are'} missing`}
      detail="Their files were moved or deleted."
    >
      <Button
        size="sm"
        variant="outline"
        className="h-7 text-xs shrink-0"
        onClick={() => setConfirming(true)}
      >
        Remove missing maps
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Remove missing maps?"
        description={`This removes the ${count} whose files are gone, with their names and tags. This can't be undone.`}
        confirmLabel="Remove missing maps"
        loadingLabel="Removing…"
        onConfirm={() => remove.mutate()}
        isLoading={remove.isPending}
      />
    </ActionRow>
  )
}

function ActionRow({
  title,
  detail,
  children,
}: {
  title: string
  detail: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-sm text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">{detail}</p>
      </div>
      {children}
    </div>
  )
}
