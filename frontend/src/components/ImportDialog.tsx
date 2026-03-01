import { useCallback, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { DndContext, DragOverlay } from '@dnd-kit/core'
import { Upload, FolderOpen, Loader2, Check, X, Ban } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useImportState } from '@/hooks/useImportState'
import { useImportDnd } from '@/hooks/useImportDnd'
import { removeImportState } from '@/lib/importStorage'
import { importApi } from '@/lib/api'
import { ImportUploadPane } from './import/ImportUploadPane'
import { ImportGroupNav } from './import/ImportGroupNav'
import { ImportGroupContent } from './import/ImportGroupContent'
import { ImportDonePane } from './import/ImportDonePane'
import { DragOverlayContent } from './import/shared/dnd'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onActiveChange?: (active: boolean) => void
  /** Called when the dialog's internal jobId changes (e.g. after upload init). */
  onJobIdChange?: (jobId: string | null) => void
  /** Pass a job ID to reconnect to an existing import (from the tray). */
  reconnectJobId?: string
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
  const dnd = useImportDnd(s)
  const { state, uploading, jobId, reset } = s.workflow

  // Notify parent when our internal jobId changes so the dialog manager
  // can track which job is mounted and avoid unnecessary remounts.
  const onJobIdChangeRef = useRef(onJobIdChange)
  onJobIdChangeRef.current = onJobIdChange
  useEffect(() => {
    onJobIdChangeRef.current?.(jobId)
  }, [jobId])
  const { groups } = s.files
  const { saveNow } = s.persistence

  const handleCancel = useCallback(async () => {
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
      saveNow()
      onOpenChange(false)
      return
    }
    // If done, clean up localStorage entry and invalidate queries
    if (state === 'done') {
      if (jobId) removeImportState(jobId)
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['search'] })
      queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
      reset()
      onOpenChange(false)
      return
    }
    // If in preview with pending groups, save state for later
    if (state === 'preview' && groups.some((g) => g.status === 'pending' && !g.skip)) {
      saveNow()
      reset()
      onOpenChange(false)
      return
    }
    // If in preview with no pending groups but completed groups, auto-finalize
    if (state === 'preview' && groups.some((g) => g.status === 'completed')) {
      if (jobId) {
        importApi.finalize(jobId).catch(() => {})
        removeImportState(jobId)
      }
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['search'] })
      queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
      reset()
      onOpenChange(false)
      return
    }
    // Otherwise (upload state, or preview with no groups), just reset
    reset()
    onOpenChange(false)
  }, [state, uploading, jobId, groups, queryClient, reset, saveNow, onOpenChange])

  const isWide = state === 'preview' || state === 'processing'

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className={`${isWide ? 'max-w-5xl h-[85vh]' : 'max-w-lg'} overflow-hidden flex flex-col p-0 gap-0`}
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
            {state === 'preview' && (
              <>
                <FolderOpen className="h-5 w-5 text-primary shrink-0" />
                Review Import
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
            {state === 'preview' &&
              jobId &&
              s.files.pendingGroups.length === 0 &&
              s.files.completedCount > 0 && (
                <button
                  onClick={s.confirm.handleFinalize}
                  className="flex items-center gap-1.5 px-3 h-7 rounded text-sm bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                  title="Finish import — all groups have been submitted"
                >
                  <Check className="h-3.5 w-3.5" />
                  Done
                </button>
              )}
            {state === 'preview' && jobId && (
              <button
                onClick={handleCancel}
                className="flex items-center gap-1.5 px-2.5 h-7 rounded text-sm text-muted-foreground hover:text-destructive hover:bg-secondary transition-colors"
                title="Cancel and discard this import"
              >
                <Ban className="h-3.5 w-3.5" />
                Cancel
              </button>
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

        {/* Preview / Processing — two-column layout */}
        {(state === 'preview' || state === 'processing') && groups.length > 0 && (
          <DndContext
            sensors={dnd.sensors}
            onDragStart={dnd.handleDragStart}
            onDragEnd={dnd.handleDragEnd}
          >
            <div className="flex min-h-0 flex-1 overflow-hidden">
              {groups.length > 1 && (
                <ImportGroupNav
                  groups={s.files.groups}
                  activeTab={s.files.activeTab}
                  state={state}
                  totalFiles={s.files.totalFiles}
                  pendingGroupCount={s.files.pendingGroups.length}
                  canImportAll={s.confirm.canImportAll}
                  canMergeAll={s.confirm.canMergeAll}
                  activeDrag={dnd.activeDrag}
                  onSelectTab={s.files.setActiveTab}
                  onUpdateGroup={s.editing.updateGroup}
                  onMergeGroups={s.editing.mergeGroups}
                  onMergeAllGroups={s.editing.mergeAllGroups}
                  onConfirmAll={s.confirm.handleConfirmAll}
                />
              )}
              <ImportGroupContent s={s} activeDrag={dnd.activeDrag} />
            </div>
            <DragOverlay dropAnimation={null}>
              <DragOverlayContent activeDrag={dnd.activeDrag} />
            </DragOverlay>
          </DndContext>
        )}

        {/* Done */}
        {state === 'done' && (
          <ImportDonePane completedCount={s.files.completedCount} onClose={handleClose} />
        )}
      </DialogContent>
    </Dialog>
  )
}
