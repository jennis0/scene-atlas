import { useEffect, useRef, Suspense, lazy, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { searchApi } from '@/lib/api'
import { invalidateGalleryQueries } from '@/lib/queryKeys'
import type { SeedImage } from '@/types'
import { ImageGrid } from '@/components/ImageGrid'
import { GroupGrid } from '@/components/GroupGrid'
import { ImageViewer } from '@/components/ImageViewer'
import { ImportDialog } from '@/components/imports/ImportDialog'
import { ImportReportDialog } from '@/components/imports/ImportReportDialog'
import { isFinished, outcomeText } from '@/components/imports/format'
import { ActivityDock } from '@/components/ActivityDock'
const EditGroupDialog = lazy(() => import('@/components/EditGroupDialog'))
import { TagManagementDialog } from '@/components/TagManagementDialog'
import { MergeGroupPicker } from '@/components/MergeGroupPicker'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { LibraryInfoDialog } from '@/components/LibraryInfoDialog'
import { EmptyLibraryWelcome } from '@/components/EmptyLibraryWelcome'
import { GalleryHeader } from '@/components/GalleryHeader'
import { useGallerySearch } from '@/hooks/useGallerySearch'
import { useGalleryDialogs } from '@/hooks/useGalleryDialogs'
import { useEmbeddingStatus } from '@/hooks/useEmbeddingStatus'
import { getImportManager } from '@/lib/import/ImportManager'
import { useImportManagerSnapshot, useImportPollingLifecycle } from '@/lib/import/useImports'
import { useBackgroundJobs } from '@/hooks/useBackgroundJobs'
import { useTileSize } from '@/hooks/useTileSize'
import { TILE_SIZES } from '@/lib/constants'
import { Button } from '@/components/ui/button'

export function Gallery() {
  const queryClient = useQueryClient()
  const search = useGallerySearch()
  const dialogs = useGalleryDialogs(search.displayImages)
  const { setReportJobId } = dialogs

  // Memoize seedImages so useEditGroupLoad doesn't re-fire on every render
  const seedImages = useMemo(
    () => (search.viewMode === 'grouped' ? dialogs.editAllSeedImages : search.displayImages),
    [search.viewMode, dialogs.editAllSeedImages, search.displayImages],
  )

  const embedding = useEmbeddingStatus()
  const { tileSize, setTileSize } = useTileSize()
  const backgroundJobs = useBackgroundJobs()
  useImportPollingLifecycle()
  const importSnapshot = useImportManagerSnapshot()
  const sentinelRef = useRef<HTMLDivElement>(null)

  // Infinite scroll sentinel for grouped view
  useEffect(() => {
    if (search.viewMode !== 'grouped') return
    if (!sentinelRef.current) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && search.hasNextPage && !search.isFetchingNextPage) {
          search.fetchNextPage()
        }
      },
      { rootMargin: '200px' },
    )

    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [search])

  // Images appear in the gallery as they're imported: refresh at most every few
  // seconds while the imported count grows.
  const importedTotal = importSnapshot.jobs.reduce((sum, j) => sum + j.counts.done, 0)
  const lastRefreshRef = useRef({ total: importedTotal, at: 0 })
  useEffect(() => {
    const last = lastRefreshRef.current
    if (importedTotal === last.total) return
    const wait = Math.max(0, 4000 - (Date.now() - last.at))
    const timer = setTimeout(() => {
      lastRefreshRef.current = { total: importedTotal, at: Date.now() }
      invalidateGalleryQueries(queryClient)
    }, wait)
    return () => clearTimeout(timer)
  }, [importedTotal, queryClient])

  // An import whose dialog is on screen already shows its outcome: no toast.
  const watchedJobRef = useRef<string | null>(null)
  useEffect(() => {
    watchedJobRef.current = dialogs.importDialog.open
      ? dialogs.importDialog.jobId
      : dialogs.reportJobId
  }, [dialogs.importDialog, dialogs.reportJobId])

  // Tell the user when an import finishes, including when files had problems.
  useEffect(() => {
    return getImportManager().onJobFinished((job) => {
      invalidateGalleryQueries(queryClient)
      if (job.status === 'cancelled' || watchedJobRef.current === job.id) return
      const action = { label: 'View report', onClick: () => setReportJobId(job.id) }
      const description = outcomeText(job.counts)
      if (job.counts.failed > 0) {
        toast.warning(`${job.label ?? 'Import'} finished with problems`, {
          description,
          duration: 10000,
          action,
        })
      } else {
        toast.success(`${job.label ?? 'Import'} finished`, { description, duration: 8000, action })
      }
    })
  }, [queryClient, setReportJobId])

  // The dock opens a running import's progress, or a finished import's report.
  const openImportFromDock = (jobId: string) => {
    const job = importSnapshot.jobs.find((j) => j.id === jobId)
    if (job && isFinished(job)) dialogs.setReportJobId(jobId)
    else dialogs.openImport(jobId)
  }

  const handleOpenMassEdit = async () => {
    if (dialogs.editAllLoading) return

    if (search.viewMode === 'individual') {
      dialogs.setShowMassEdit(true)
      return
    }

    // Grouped view: fetch all matching images with current filters
    if (search.viewMode === 'grouped' && search.totalGroups <= 500) {
      dialogs.setEditAllLoading(true)
      try {
        const response = await searchApi.groups({
          ...search.groupSearchParams,
          limit: search.totalGroups,
          offset: 0,
          include_all_image_ids: true,
        })
        const seedImages: SeedImage[] = response.groups.flatMap((g) =>
          (g.all_image_ids ?? []).map((imgId) => ({ id: imgId, group_id: g.group_id })),
        )
        dialogs.setEditAllSeedImages(seedImages)
        dialogs.setShowMassEdit(true)
      } catch (error) {
        toast.error('Failed to load images for bulk edit')
        console.error(error)
      } finally {
        dialogs.setEditAllLoading(false)
      }
    }
  }

  return (
    <div className="flex h-screen flex-col">
      {/* A button, not an href: the app routes on the URL hash */}
      <button
        type="button"
        onClick={() => document.getElementById('results')?.focus()}
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-md focus:bg-popover focus:px-3 focus:py-2 focus:text-sm focus:text-foreground focus:shadow-lg"
      >
        Skip to results
      </button>
      <GalleryHeader
        search={{ ...search, editAllLoading: dialogs.editAllLoading }}
        embeddingStatus={embedding.status}
        embeddingError={embedding.error}
        onOpenImport={() => dialogs.openImport()}
        onOpenTagManagement={() => dialogs.setShowTagManagement(true)}
        onOpenSystemInfo={() => dialogs.setShowSystemInfo(true)}
        onOpenMassEdit={handleOpenMassEdit}
        displayImageCount={search.displayImages.length}
        tileSize={tileSize}
        onTileSizeChange={setTileSize}
      />

      <main
        id="results"
        tabIndex={-1}
        aria-label="Results"
        className="flex-1 overflow-hidden focus:outline-none"
        style={{ boxShadow: 'inset 0 8px 24px rgba(0,0,0,0.4)' }}
      >
        {search.isSearching ? (
          <div className="flex h-full items-center justify-center">
            <p role="status" className="text-muted-foreground">
              Searching&hellip;
            </p>
          </div>
        ) : !search.hasActiveSearch && (search.facets?.total_images ?? 0) === 0 ? (
          <EmptyLibraryWelcome
            embeddingReady={embedding.status === 'ready'}
            onImport={() => dialogs.openImport()}
          />
        ) : (
            search.viewMode === 'grouped'
              ? search.imageGroups.length === 0
              : search.displayImages.length === 0
          ) ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center max-w-md">
              <p className="text-muted-foreground mb-2">
                {search.hasActiveSearch
                  ? search.viewMode === 'grouped'
                    ? 'No groups match your search'
                    : 'No images match your search'
                  : search.viewMode === 'grouped'
                    ? 'No groups available'
                    : 'No images available'}
              </p>
              {search.isSemantic && (
                <p className="text-sm text-muted-foreground">
                  Try: &quot;abandoned mine with crystals&quot; or &quot;winter forest temple&quot;
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
            </div>
          </div>
        ) : search.viewMode === 'individual' ? (
          <div className="h-full max-w-[1400px] mx-auto">
            <ImageGrid
              images={search.displayImages}
              tileWidth={TILE_SIZES[tileSize]}
              onImageClick={(image, index) => dialogs.setSelectedImage({ image, index })}
            />
          </div>
        ) : (
          <div className="h-full overflow-y-auto">
            <div className="max-w-[1400px] mx-auto">
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

            <div ref={sentinelRef} className="flex justify-center py-8">
              {search.isFetchingNextPage ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              ) : !search.hasNextPage ? (
                <p className="text-sm text-muted-foreground">
                  All {search.totalGroups} groups loaded
                </p>
              ) : null}
            </div>
          </div>
        )}
      </main>

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

        {/* Group editor over every group an import created (from the import report) */}
        <EditGroupDialog
          groupIds={dialogs.reviewGroupIds ?? undefined}
          open={dialogs.reviewGroupIds !== null}
          onClose={() => dialogs.setReviewGroupIds(null)}
          onSave={() => dialogs.invalidateGallery()}
        />

        {/* Mass-edit dialog -- all images in current search results */}
        <EditGroupDialog
          seedImages={seedImages}
          open={dialogs.showMassEdit}
          onClose={() => {
            dialogs.setShowMassEdit(false)
            dialogs.setEditAllSeedImages([])
          }}
          onSave={() => {
            dialogs.setShowMassEdit(false)
            dialogs.invalidateGallery()
          }}
        />
      </Suspense>

      {/* Import dialog: start a new import, or follow one in progress */}
      <ImportDialog
        jobId={dialogs.importDialog.jobId}
        open={dialogs.importDialog.open}
        onClose={dialogs.closeImport}
        onStarted={(jobId) => dialogs.openImport(jobId)}
        onOpenReport={(jobId) => {
          dialogs.closeImport()
          dialogs.setReportJobId(jobId)
        }}
        onOpenGroup={(groupId) => {
          dialogs.closeImport()
          dialogs.setEditGroupId(groupId)
        }}
      />

      <ImportReportDialog
        jobId={dialogs.reportJobId}
        open={dialogs.reportJobId !== null}
        onClose={() => dialogs.setReportJobId(null)}
        onOpenGroup={(groupId) => {
          dialogs.setReportJobId(null)
          dialogs.setEditGroupId(groupId)
        }}
        onReviewGroups={(groupIds) => {
          dialogs.setReportJobId(null)
          dialogs.setReviewGroupIds(groupIds)
        }}
        onUndone={() => dialogs.invalidateGallery()}
      />

      <TagManagementDialog
        open={dialogs.showTagManagement}
        onClose={() => dialogs.setShowTagManagement(false)}
      />

      <LibraryInfoDialog
        open={dialogs.showSystemInfo}
        onClose={() => dialogs.setShowSystemInfo(false)}
      />

      <ActivityDock backgroundJobs={backgroundJobs.jobs} onOpenImport={openImportFromDock} />

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

      <MergeGroupPicker
        open={dialogs.mergeSourceGroup !== null}
        onClose={() => dialogs.setMergeSourceGroup(null)}
        sourceGroupId={dialogs.mergeSourceGroup?.groupId}
        excludeGroupId={dialogs.mergeSourceGroup?.groupId}
        currentGroupName={dialogs.mergeSourceGroup?.baseName}
        onMergeComplete={() => dialogs.setMergeSourceGroup(null)}
      />
    </div>
  )
}
