import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { plural } from '@/components/imports/format'
import { libraryApi, type LibraryStatus } from '@/lib/api/libraryApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { QUERY_KEYS, invalidateGalleryQueries } from '@/lib/queryKeys'

type Linked = NonNullable<LibraryStatus['linked']>

/**
 * Desktop app: "Stop using this folder", the way out of linking the wrong folder. After the
 * user confirms the count, the folder's maps leave the library (DELETE /library/linked;
 * the files are never touched), then the desktop app drops the folder from its config and
 * restarts the backend, which reloads the page.
 */
export function StopUsingFolder({ linked }: { linked: Linked }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const stop = async () => {
    const api = window.electronAPI
    if (!api) return
    setBusy(true)
    try {
      await libraryApi.removeLinked()
      const dirs = await api.getStorageDirs()
      const outcome = await api.applyLibrary({
        appData: dirs.appData,
        store: dirs.store,
        linked: null,
      })
      // Restarted: the page reloads. Otherwise only an error comes back.
      if (outcome.error) toast.error(outcome.error)
      if (outcome.error || !outcome.restarted) {
        setBusy(false)
        setConfirming(false)
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Couldn't stop using this folder."))
      setBusy(false)
      setConfirming(false)
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="destructive"
        className="h-7 text-xs shrink-0"
        onClick={() => setConfirming(true)}
      >
        Stop using
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Stop using this folder?"
        description={
          <>
            This removes the {plural(linked.image_count, 'map')} in <strong>{linked.name}</strong>{' '}
            from your library, with their names and tags. The files in the folder stay as they are.
            Scene Atlas then restarts.
          </>
        }
        confirmLabel="Stop using this folder"
        loadingLabel="Stopping…"
        onConfirm={() => void stop()}
        isLoading={busy}
      />
    </>
  )
}

/** A detached folder (no longer configured): remove its maps, which can't be opened. */
export function RemoveDetachedMaps({ linked }: { linked: Linked }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const remove = async () => {
    setBusy(true)
    try {
      const { removed } = await libraryApi.removeLinked()
      toast.success(`${plural(removed, 'map')} removed.`)
      invalidateGalleryQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.libraryStatus })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.systemInfo })
      setConfirming(false)
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Couldn't remove the maps."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="destructive"
        className="h-7 text-xs shrink-0"
        onClick={() => setConfirming(true)}
      >
        Remove its maps
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Remove this folder's maps?"
        description={
          <>
            This removes the {plural(linked.image_count, 'map')} from <strong>{linked.name}</strong>
            , with their names and tags. This can&apos;t be undone.
          </>
        }
        confirmLabel="Remove maps"
        loadingLabel="Removing…"
        onConfirm={() => void remove()}
        isLoading={busy}
      />
    </>
  )
}
