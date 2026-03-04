import { useEffect, Suspense, lazy } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Upload, Mountain } from 'lucide-react'
import { groupApi } from '@/lib/api'
import { ImageGrid } from '@/components/ImageGrid'
import { GroupGrid } from '@/components/GroupGrid'
import { ImageViewer } from '@/components/ImageViewer'
import { ImportDialog } from '@/components/ImportDialog'
import { ActivityDock } from '@/components/ActivityDock'
const EditGroupDialog = lazy(() => import('@/components/EditGroupDialog'))
import { TagManagementDialog } from '@/components/TagManagementDialog'
import { MergeGroupPicker } from '@/components/MergeGroupPicker'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { SystemInfoDialog } from '@/components/SystemInfoDialog'
import { ImportSummaryDialog } from '@/components/ImportSummaryDialog'
import { GalleryHeader } from '@/components/GalleryHeader'
import { useGallerySearch } from '@/hooks/useGallerySearch'
import { useGalleryDialogs } from '@/hooks/useGalleryDialogs'
import { useActiveImports } from '@/hooks/useActiveImports'
import { useBackgroundJobs } from '@/hooks/useBackgroundJobs'
import { Button } from '@/components/ui/button'

// ---------------------------------------------------------------------------

export function Gallery() {
  const queryClient = useQueryClient()
  const search = useGallerySearch()
  const dialogs = useGalleryDialogs(search.displayImages)
  const activeImports = useActiveImports()
  const backgroundJobs = useBackgroundJobs()

  // Invalidate gallery queries and show review toast whenever a background import finishes
  useEffect(() => {
    return activeImports.onJobCompleted((job) => {
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['search'] })
      queryClient.invalidateQueries({ queryKey: ['searchFacets'] })

      const groupCount = job.totalGroups
      const fileCount = job.totalFiles
      const description =
        groupCount === 1
          ? `${fileCount} image${fileCount !== 1 ? 's' : ''} imported`
          : `${groupCount} groups, ${fileCount} image${fileCount !== 1 ? 's' : ''} imported`

      toast.success('Import complete', {
        description,
        duration: 8000,
        action: {
          label: 'Review',
          onClick: () => dialogs.setImportLiveJobId(job.jobId),
        },
      })
    })
  }, [activeImports, queryClient, dialogs])

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <GalleryHeader
        search={search}
        onOpenImport={() => dialogs.openImportDialog()}
        onOpenTagManagement={() => dialogs.setShowTagManagement(true)}
        onOpenSystemInfo={() => dialogs.setShowSystemInfo(true)}
        onOpenMassEdit={() => dialogs.setShowMassEdit(true)}
        displayImageCount={search.displayImages.length}
      />

      {/* Main content */}
      <main
        className="flex-1 overflow-hidden"
        style={{ boxShadow: 'inset 0 8px 24px rgba(0,0,0,0.4)' }}
      >
        {search.isSearching ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-muted-foreground">Searching&hellip;</p>
          </div>
        ) : search.displayImages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center max-w-md">
              {!search.hasActiveSearch && (search.facets?.total_images ?? 0) === 0 ? (
                <>
                  <Mountain className="h-10 w-10 text-muted-foreground/30 mx-auto mb-4" />
                  <p className="text-muted-foreground mb-1">Your library is empty</p>
                  <p className="text-sm text-muted-foreground/70 mb-5">
                    Import some battlemaps and scenes to get started.
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-primary border-primary/40 hover:bg-primary/10"
                    onClick={() => dialogs.openImportDialog()}
                  >
                    <Upload className="h-3.5 w-3.5 mr-1.5" />
                    Import
                  </Button>
                </>
              ) : (
                <>
                  <p className="text-muted-foreground mb-2">
                    {search.hasActiveSearch ? 'No images match your search' : 'No images available'}
                  </p>
                  {search.isSemantic && (
                    <p className="text-sm text-muted-foreground">
                      Try: &quot;abandoned mine with crystals&quot; or &quot;winter forest
                      temple&quot;
                    </p>
                  )}
                  {search.minScore > 0 && (
                    <p className="text-sm text-muted-foreground">
                      Lower the relevance threshold to see more results.
                    </p>
                  )}
                  {search.hasActiveSearch && (
                    <Button variant="outline" size="sm" onClick={search.clearAll} className="mt-4">
                      Clear search
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        ) : search.viewMode === 'individual' ? (
          <div className="h-full max-w-[1400px] mx-auto">
            <ImageGrid
              images={search.displayImages}
              onImageClick={(image, index) => dialogs.setSelectedImage({ image, index })}
            />
          </div>
        ) : (
          <div className="h-full max-w-[1400px] mx-auto">
            <GroupGrid
              groups={search.imageGroups}
              onGroupClick={(group) =>
                dialogs.setSelectedImage({ image: group.heroImage, index: 0 })
              }
              onEditGroup={(g) => g.groupId !== null && dialogs.setEditGroupId(g.groupId)}
              onDeleteGroup={(g) => dialogs.setDeleteConfirmGroup(g)}
              onMergeGroup={(g) => dialogs.setMergeSourceGroup(g)}
            />
          </div>
        )}
      </main>

      {/* Image viewer modal */}
      {dialogs.selectedImage && (
        <ImageViewer
          image={dialogs.selectedImage.image}
          onClose={() => dialogs.setSelectedImage(null)}
          onNext={
            dialogs.selectedImage.index < search.displayImages.length - 1
              ? dialogs.handleNext
              : undefined
          }
          onPrevious={dialogs.selectedImage.index > 0 ? dialogs.handlePrevious : undefined}
          onImageChange={(newImage) => {
            dialogs.setSelectedImage((prev) => (prev ? { ...prev, image: newImage } : null))
          }}
          onEditGroup={(id) => {
            dialogs.setSelectedImage(null)
            dialogs.setEditGroupId(id)
          }}
          onDelete={(deletedId) => {
            const idx = dialogs.selectedImage!.index
            const remaining = search.displayImages.filter((img) => img.id !== deletedId)
            if (remaining.length === 0) {
              dialogs.setSelectedImage(null)
            } else {
              const nextIdx = Math.min(idx, remaining.length - 1)
              dialogs.setSelectedImage({ image: remaining[nextIdx], index: nextIdx })
            }
          }}
        />
      )}

      {/* Edit group dialogs -- lazy-loaded since they pull in @dnd-kit */}
      <Suspense fallback={null}>
        {/* Edit group dialog -- single group (from image viewer) */}
        <EditGroupDialog
          groupId={dialogs.editGroupId}
          open={dialogs.editGroupId !== null}
          onClose={() => dialogs.setEditGroupId(null)}
          onSave={() => {
            dialogs.setEditGroupId(null)
            dialogs.invalidateGallery()
          }}
        />

        {/* Live import-review dialog -- opened by clicking an active or completed job in the tray */}
        <EditGroupDialog
          importJobId={dialogs.importLiveJobId ?? undefined}
          importJobInitiallyDone={['completed', 'awaiting_input'].includes(
            activeImports.jobs.find((j) => j.jobId === dialogs.importLiveJobId)?.status ?? '',
          )}
          open={dialogs.importLiveJobId !== null}
          onClose={() => dialogs.setImportLiveJobId(null)}
          onSave={(reviewedImportJobId) => {
            // onClose() already cleared importLiveJobId — don't set it to null here.
            // importJobId is passed directly from handleDone so we don't need a ref.
            dialogs.invalidateGallery()
            if (reviewedImportJobId) {
              activeImports.dismissJob(reviewedImportJobId)
            }
          }}
        />

        {/* Mass-edit dialog -- all images in current search results */}
        <EditGroupDialog
          seedImages={search.displayImages}
          open={dialogs.showMassEdit}
          onClose={() => dialogs.setShowMassEdit(false)}
          onSave={() => {
            dialogs.setShowMassEdit(false)
            dialogs.invalidateGallery()
          }}
        />
      </Suspense>

      {/* Import dialog -- key forces remount so each open starts fresh */}
      <ImportDialog
        key={dialogs.importDialogKey}
        open={dialogs.importDialogJobId !== null}
        reconnectJobId={
          dialogs.importDialogJobId === 'new' ? undefined : (dialogs.importDialogJobId ?? undefined)
        }
        onOpenChange={(open) => {
          if (!open) {
            dialogs.setImportDialogJobId(null)
            activeImports.refresh()
          }
        }}
        onActiveChange={() => activeImports.refresh()}
        onJobIdChange={dialogs.setMountedImportJob}
      />

      <TagManagementDialog
        open={dialogs.showTagManagement}
        onClose={() => dialogs.setShowTagManagement(false)}
      />

      <SystemInfoDialog
        open={dialogs.showSystemInfo}
        onClose={() => dialogs.setShowSystemInfo(false)}
      />

      {/* Import summary dialog -- opened by clicking a failed/broken job in the tray */}
      <ImportSummaryDialog
        jobId={dialogs.importSummaryJobId}
        open={dialogs.importSummaryJobId !== null}
        onClose={() => dialogs.setImportSummaryJobId(null)}
        onCancel={(jobId) => {
          activeImports.cancelJob(jobId)
          dialogs.setImportSummaryJobId(null)
        }}
      />

      {/* Activity dock -- bottom-right floating panel showing all jobs */}
      <ActivityDock
        jobs={activeImports.jobs}
        hasActive={activeImports.hasActive}
        connectionLost={activeImports.connectionLost}
        backgroundJobs={backgroundJobs.jobs}
        hasActiveJobs={backgroundJobs.hasActive}
        onOpenJob={(jobId) => {
          const job = activeImports.jobs.find((j) => j.jobId === jobId)
          if (job?.status === 'failed' || job?.status === 'broken') {
            // Failed/broken jobs open the import summary dialog
            dialogs.setImportSummaryJobId(jobId)
          } else if (
            job?.status === 'completed' ||
            job?.status === 'active' ||
            job?.status === 'running' ||
            job?.status === 'awaiting_input'
          ) {
            // Active, completed, and awaiting_input jobs open EditGroupDialog in live-review mode:
            // - active: shows pending group stubs + any already-completed groups
            // - completed/awaiting_input: all groups load immediately, no stubs
            dialogs.setImportLiveJobId(jobId)
          } else if (job?.status === 'staging') {
            dialogs.openImportDialog(jobId)
          }
          // 'uploading' jobs are not clickable — upload progress is shown
          // directly in the ActivityDock card. The upload state (XHR handles,
          // file data) is ephemeral and can't be restored in a new dialog.
        }}
        onDismissJob={activeImports.dismissJob}
        onCancelJob={activeImports.cancelJob}
        onRefresh={activeImports.refresh}
      />

      {/* Delete group confirmation */}
      <ConfirmDialog
        open={dialogs.deleteConfirmGroup !== null}
        onOpenChange={(v) => !v && dialogs.setDeleteConfirmGroup(null)}
        title="Delete Group"
        description={
          <>
            Are you sure you want to delete <strong>{dialogs.deleteConfirmGroup?.baseName}</strong>{' '}
            and all {dialogs.deleteConfirmGroup?.totalScenes} image
            {dialogs.deleteConfirmGroup?.totalScenes !== 1 ? 's' : ''}? This cannot be undone.
          </>
        }
        onConfirm={dialogs.handleGroupDeleteConfirm}
        isLoading={dialogs.deleting}
      />

      {/* Merge group picker */}
      <MergeGroupPicker
        open={dialogs.mergeSourceGroup !== null}
        onClose={() => dialogs.setMergeSourceGroup(null)}
        excludeGroupId={dialogs.mergeSourceGroup?.groupId}
        currentGroupName={dialogs.mergeSourceGroup?.baseName}
        onSelect={async (targetGroup) => {
          if (!dialogs.mergeSourceGroup?.groupId) return
          try {
            await groupApi.merge(dialogs.mergeSourceGroup.groupId, targetGroup.id)
            // Await search refetch so stale group cards are removed before
            // the picker closes and the user can interact with the gallery.
            await queryClient.refetchQueries({ queryKey: ['search'] })
            queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
            dialogs.setMergeSourceGroup(null)
          } catch (err) {
            console.error('Failed to merge groups:', err)
          }
        }}
      />
    </div>
  )
}
