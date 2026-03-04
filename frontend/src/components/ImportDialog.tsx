import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Upload, Loader2, Check, X, AlertCircle } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useImportState } from '@/hooks/useImportState'
import { removeImportState } from '@/lib/importStorage'
import { importApi } from '@/lib/api'
import { invalidateGalleryQueries } from '@/lib/queryKeys'
import { ImportUploadPane } from './import/ImportUploadPane'
import { ImportDonePane } from './import/ImportDonePane'
import type { EditableGroupState } from '@/types'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onActiveChange?: (active: boolean) => void
  /** Called when the dialog's internal jobId changes (e.g. after upload init). */
  onJobIdChange?: (jobId: string | null) => void
  /** Pass a job ID to reconnect to an existing import (from the tray). */
  reconnectJobId?: string
}

function GroupStatusRow({ group }: { group: EditableGroupState }) {
  const { status, group_name, author, total, processed, failed } = group
  return (
    <div className="flex items-center gap-3 py-2.5 px-4 rounded-lg bg-secondary/40">
      <div className="shrink-0">
        {status === 'running' && <Loader2 className="h-4 w-4 text-primary animate-spin" />}
        {status === 'completed' && <Check className="h-4 w-4 text-green-500" />}
        {status === 'failed' && <AlertCircle className="h-4 w-4 text-destructive" />}
        {status === 'pending' && <Loader2 className="h-4 w-4 text-muted-foreground animate-spin" />}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{group_name}</p>
        {author && <p className="text-xs text-muted-foreground truncate">{author}</p>}
      </div>
      <div className="text-xs text-muted-foreground shrink-0">
        {status === 'completed'
          ? `${processed} / ${total}`
          : status === 'failed'
            ? `${failed} failed`
            : `${processed} / ${total}`}
      </div>
    </div>
  )
}

export function ImportDialog({
  open,
  onOpenChange,
  onActiveChange,
  onJobIdChange,
  reconnectJobId,
}: ImportDialogProps) {
  const queryClient = useQueryClient()
  const s = useImportState(onActiveChange, reconnectJobId)
  const { state, uploading, jobId, reset } = s.workflow
  const [confirmingCancel, setConfirmingCancel] = useState(false)

  // Notify parent when our internal jobId changes so the dialog manager
  // can track which job is mounted and avoid unnecessary remounts.
  const onJobIdChangeRef = useRef(onJobIdChange)
  onJobIdChangeRef.current = onJobIdChange
  useEffect(() => {
    onJobIdChangeRef.current?.(jobId)
  }, [jobId])

  // Auto-close when processing starts — ActivityDock tracks progress from here.
  const onOpenChangeRef = useRef(onOpenChange)
  onOpenChangeRef.current = onOpenChange
  useEffect(() => {
    if (state === 'processing') {
      s.persistence.saveNow()
      onOpenChangeRef.current(false)
    }
  }, [state, s.persistence])

  const { groups } = s.files
  const totalProcessed = groups.reduce((sum, g) => sum + g.processed, 0)

  const handleCancel = useCallback(async () => {
    setConfirmingCancel(false)
    if (jobId) {
      try {
        await importApi.cancel(jobId)
      } catch {
        /* ignore */
      }
      removeImportState(jobId)
    }
    reset()
    onOpenChange(false)
  }, [jobId, reset, onOpenChange])

  const handleClose = useCallback(() => {
    // If uploading, just hide — upload continues in background, localStorage has job_id
    if (state === 'upload' && uploading) {
      onOpenChange(false)
      return
    }
    // If processing, just hide the dialog — tray will show progress
    if (state === 'processing') {
      s.persistence.saveNow()
      onOpenChange(false)
      return
    }
    // If done, clean up localStorage entry and invalidate queries
    if (state === 'done') {
      if (jobId) removeImportState(jobId)
      invalidateGalleryQueries(queryClient)
      reset()
      onOpenChange(false)
      return
    }
    // Otherwise (upload state with no active upload), just reset
    reset()
    onOpenChange(false)
  }, [state, uploading, jobId, queryClient, reset, s.persistence, onOpenChange])

  const isWide = state === 'processing'

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className={`${isWide ? 'max-w-2xl' : 'max-w-lg'} max-h-[85vh] overflow-hidden flex flex-col p-0 gap-0`}
      >
        {/* Amber stripe */}
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-xl" />

        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-3 shrink-0">
          <h2 className="font-display text-lg font-semibold flex items-center gap-2 text-foreground">
            {state === 'upload' && (
              <>
                <Upload className="h-5 w-5 text-primary shrink-0" />
                Import Scenes
              </>
            )}
            {state === 'processing' && (
              <>
                <Loader2 className="h-5 w-5 text-primary animate-spin shrink-0" />
                Processing…
              </>
            )}
            {state === 'done' && (
              <>
                <Check className="h-5 w-5 text-primary shrink-0" />
                Import Complete
              </>
            )}
          </h2>
          <div className="flex items-center gap-1">
            {state === 'upload' && jobId && (
              <button
                onClick={handleCancel}
                className="flex items-center gap-1.5 px-2.5 h-7 rounded text-sm text-muted-foreground hover:text-destructive hover:bg-secondary transition-colors"
                title="Cancel and discard this import"
              >
                Cancel
              </button>
            )}
            {state === 'processing' && jobId && !confirmingCancel && (
              <button
                onClick={() => (totalProcessed > 0 ? setConfirmingCancel(true) : handleCancel())}
                className="flex items-center gap-1.5 px-2.5 h-7 rounded text-sm text-muted-foreground hover:text-destructive hover:bg-secondary transition-colors"
                title="Cancel and remove imported images"
              >
                Cancel
              </button>
            )}
            {state === 'processing' && confirmingCancel && (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">
                  Delete {totalProcessed} imported{totalProcessed === 1 ? ' image' : ' images'}?
                </span>
                <button
                  onClick={handleCancel}
                  className="text-xs px-2 h-6 rounded bg-destructive/15 text-destructive hover:bg-destructive/25 transition-colors"
                >
                  Yes
                </button>
                <button
                  onClick={() => setConfirmingCancel(false)}
                  className="text-xs px-2 h-6 rounded bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
                >
                  No
                </button>
              </div>
            )}
            <button
              onClick={handleClose}
              className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        {/* Amber rule */}
        <div className="h-px bg-gradient-to-r from-primary/60 via-primary/20 to-transparent mx-6 shrink-0" />

        {/* Upload state */}
        {state === 'upload' && (
          <ImportUploadPane
            uploading={uploading}
            uploadError={s.workflow.uploadError}
            uploadPhase={s.workflow.uploadPhase}
            uploadProgress={s.workflow.uploadProgress}
            skippedFiles={s.workflow.skippedFiles}
            fileInputRef={s.upload.fileInputRef}
            folderInputRef={s.upload.folderInputRef}
            onFileSelect={s.upload.handleFileSelect}
            onDrop={s.upload.handleDrop}
            defaultImageType={s.metadata.defaultImageType}
            onDefaultImageTypeChange={s.metadata.setDefaultImageType}
          />
        )}

        {/* Processing state — per-group progress list */}
        {state === 'processing' && groups.length > 0 && (
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2">
            {groups.map((group) => (
              <GroupStatusRow key={group.id} group={group} />
            ))}
          </div>
        )}

        {/* Done */}
        {state === 'done' && (
          <ImportDonePane completedCount={s.files.completedCount} onClose={handleClose} />
        )}
      </DialogContent>
    </Dialog>
  )
}
