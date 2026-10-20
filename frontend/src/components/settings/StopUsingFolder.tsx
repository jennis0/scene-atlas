import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { plural } from '@/components/imports/format'
import { libraryApi, type LinkedFolder } from '@/lib/api/libraryApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { invalidateRemovedMapsQueries } from '@/lib/queryKeys'

/**
 * Desktop app: "Stop using this folder", the way out of linking the wrong folder. After the
 * user confirms the count, the folder's maps leave the library (DELETE /library/linked;
 * the files are never touched), then the desktop app drops the folder from its config and
 * restarts the backend, which reloads the page.
 */
export function StopUsingFolder({ linked }: { linked: LinkedFolder }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const stop = async () => {
    const api = window.electronAPI
    if (!api) return
    setBusy(true)
    let removed = false
    try {
      await libraryApi.removeLinked()
      removed = true
      const dirs = await api.getStorageDirs()
      const outcome = await api.applyLibrary({
        appData: dirs.appData,
        store: dirs.store,
        linked: null,
      })
      // Restarted: the page reloads, so stay busy until it does
      if (!outcome.error && outcome.restarted) return
      if (outcome.error) toast.error(outcome.error)
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Couldn't stop using this folder."))
    }
    // The maps may be gone while the folder is still configured
    if (removed) invalidateRemovedMapsQueries(queryClient)
    setBusy(false)
    setConfirming(false)
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
            This removes the {plural(linked.image_count, 'image')} in <strong>{linked.name}</strong>{' '}
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
