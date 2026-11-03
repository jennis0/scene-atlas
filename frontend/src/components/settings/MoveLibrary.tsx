/**
 * Move the library's folders (desktop app; design/export-backup-move.md §10). The backend
 * copies a folder to its new place while the app runs, then the app restarts on it, the
 * backend finishing the copy (what changed meanwhile, the database) and checking it before
 * anything opens. The old folder is kept until the user deletes it here.
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { libraryApi } from '@/lib/api/libraryApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { MOVE_STATUS_KEY, type Movable, type useLibraryMove } from '@/hooks/useLibraryMove'

const LABELS: Record<string, string> = { app_data: 'Search data', store: 'Imported images' }

/** The Move… button on a folder's row */
export function MoveButton({
  kind,
  move,
}: {
  kind: Movable
  move: ReturnType<typeof useLibraryMove>
}) {
  const busy = move.job.isRunning || move.start.isPending
  return (
    <button
      type="button"
      onClick={() => move.start.mutate(kind)}
      disabled={busy}
      aria-label={`Move ${kind === 'appData' ? 'search data' : 'imported images'} folder`}
      className="shrink-0 rounded border border-border/50 px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
    >
      Move…
    </button>
  )
}

/** Progress, failure, and the old folders to delete */
export function MoveStatus({ move }: { move: ReturnType<typeof useLibraryMove> }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const remove = useMutation({
    mutationFn: libraryApi.deleteMovedFrom,
    onSuccess: () => {
      setConfirming(false)
      toast.success('Old folder deleted')
      void queryClient.invalidateQueries({ queryKey: MOVE_STATUS_KEY })
    },
    onError: (err) => {
      setConfirming(false)
      toast.error(getApiErrorMessage(err, "Couldn't delete the old folder"))
    },
  })
  const { job, error, movedFrom } = move

  if (job.isRunning || (job.isComplete && !error)) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>
          {job.isComplete
            ? 'Copied. Restarting on the new folder…'
            : `Copying the library: ${job.progress ?? 'starting…'} You can keep using it meanwhile.`}
        </span>
      </div>
    )
  }
  return (
    <>
      {(job.isFailed || error) && (
        <p role="alert" className="text-xs text-destructive">
          {error ?? job.error ?? 'The move failed.'} Nothing has moved.
        </p>
      )}
      {movedFrom && (
        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span className="min-w-0">
            The library was moved. The old copy is still in{' '}
            {Object.entries(movedFrom).map(([kind, path], i) => (
              <span key={kind}>
                {i > 0 && ' and '}
                <span className="font-mono break-all" title={LABELS[kind]}>
                  {path}
                </span>
              </span>
            ))}
            .
          </span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs shrink-0"
            onClick={() => setConfirming(true)}
          >
            Delete old copy
          </Button>
          <ConfirmDialog
            open={confirming}
            onOpenChange={setConfirming}
            title="Delete Old Copy"
            description="This deletes the folders the library was moved from. The library itself, in its new folders, isn't touched."
            confirmLabel="Delete"
            confirmVariant="destructive"
            loadingLabel="Deleting…"
            onConfirm={() => remove.mutate()}
            isLoading={remove.isPending}
          />
        </div>
      )}
    </>
  )
}
