import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Upload, FolderOpen, Loader2, Check, X, Ban } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useImportState } from '@/hooks/useImportState'
import { removeImportState } from '@/lib/importStorage'
import { importApi } from '@/lib/api'
import { ImportUploadPane } from './import/ImportUploadPane'
import { ImportGroupNav } from './import/ImportGroupNav'
import { ImportGroupContent } from './import/ImportGroupContent'
import { ImportDonePane } from './import/ImportDonePane'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onActiveChange?: (active: boolean) => void
  /** Pass a job ID to reconnect to an existing import (from the tray). */
  reconnectJobId?: string
}

export function ImportDialog({
  open,
  onOpenChange,
  onActiveChange,
  reconnectJobId,
}: ImportDialogProps) {
  const queryClient = useQueryClient()
  const s = useImportState(onActiveChange, reconnectJobId)
  const { jobId, reset, state, groups, saveNow } = s

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
    // Otherwise (upload state, or preview with no pending groups), just reset
    reset()
    onOpenChange(false)
  }, [state, jobId, groups, queryClient, reset, saveNow, onOpenChange])

  const isWide = s.state === 'preview' || s.state === 'processing'

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
            {s.state === 'upload' && (
              <>
                <Upload className="h-5 w-5 text-primary shrink-0" />
                Import Scenes
              </>
            )}
            {s.state === 'preview' && (
              <>
                <FolderOpen className="h-5 w-5 text-primary shrink-0" />
                Review Import
              </>
            )}
            {s.state === 'processing' && (
              <>
                <Loader2 className="h-5 w-5 text-primary animate-spin shrink-0" />
                Processing…
              </>
            )}
            {s.state === 'done' && (
              <>
                <Check className="h-5 w-5 text-primary shrink-0" />
                Import Complete
              </>
            )}
          </h2>
          <div className="flex items-center gap-1">
            {s.state === 'preview' && s.jobId && (
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
        {s.state === 'upload' && (
          <ImportUploadPane
            uploading={s.uploading}
            uploadError={s.uploadError}
            uploadPhase={s.uploadPhase}
            skippedFiles={s.skippedFiles}
            fileInputRef={s.fileInputRef}
            onFileSelect={s.handleFileSelect}
            defaultImageType={s.defaultImageType}
            onDefaultImageTypeChange={s.setDefaultImageType}
          />
        )}

        {/* Preview / Processing — two-column layout */}
        {(s.state === 'preview' || s.state === 'processing') && s.groups.length > 0 && (
          <div className="flex min-h-0 flex-1 overflow-hidden">
            {s.groups.length > 1 && (
              <ImportGroupNav
                groups={s.groups}
                activeTab={s.activeTab}
                state={s.state}
                totalFiles={s.totalFiles}
                pendingGroupCount={s.pendingGroups.length}
                canImportAll={s.canImportAll}
                onSelectTab={s.setActiveTab}
                onUpdateGroup={s.updateGroup}
                onMergeGroups={s.mergeGroups}
                onConfirmAll={s.handleConfirmAll}
              />
            )}
            <ImportGroupContent s={s} />
          </div>
        )}

        {/* Done */}
        {s.state === 'done' && (
          <ImportDonePane completedCount={s.completedCount} onClose={handleClose} />
        )}
      </DialogContent>
    </Dialog>
  )
}
