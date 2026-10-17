import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { toast } from 'sonner'
import { imageApi, tagApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { filenameStem } from '@/lib/format'
import { QUERY_KEYS, invalidateGalleryQueries } from '@/lib/queryKeys'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { isAnyDialogOpen } from '@/components/ui/dialogStack'
import { useModalLayer } from '@/components/ui/modalLayer'
import { useSceneFilters } from '@/hooks/useSceneFilters'
import { ViewerStage } from '@/components/viewer/ViewerStage'
import { ViewerToolbar } from '@/components/viewer/ViewerToolbar'
import { ImageNameEditor } from '@/components/viewer/ImageNameEditor'
import { ImageProperties, type ImagePatch } from '@/components/viewer/ImageProperties'
import { ImageTags } from '@/components/viewer/ImageTags'
import { ScenePanel } from '@/components/viewer/ScenePanel'
import type { Image } from '@/types'

interface ImageViewerProps {
  image: Image
  onClose: () => void
  onNext?: () => void
  onPrevious?: () => void
  onImageChange?: (image: Image) => void
  onEditGroup?: (groupId: number) => void
  onDelete?: (imageId: number) => void
}

export function ImageViewer({
  image,
  onClose,
  onNext,
  onPrevious,
  onImageChange,
  onEditGroup,
  onDelete,
}: ImageViewerProps) {
  const queryClient = useQueryClient()

  // Fresh data for the displayed image; initialData avoids flash on navigation
  const { data: displayImage } = useQuery({
    queryKey: QUERY_KEYS.image(image.id),
    queryFn: () => imageApi.get(image.id),
    initialData: image,
  })

  const { data: scenes } = useQuery({
    queryKey: QUERY_KEYS.scenes(image.id),
    queryFn: () => imageApi.getScenes(image.id),
    placeholderData: keepPreviousData,
  })

  const sceneFilters = useSceneFilters(scenes)
  const resetSceneFilters = sceneFilters.reset

  const viewerRef = useRef<HTMLDivElement>(null)
  useModalLayer(viewerRef, true)
  // Focus the viewer itself on open: screen readers announce the dialog, and the
  // arrow keys work straight away.
  useEffect(() => {
    viewerRef.current?.focus({ preventScroll: true })
  }, [])

  const scrollContainerRef = useRef<HTMLDivElement>(null)
  // Set before a within-group variant click so the reset effect keeps the UI state.
  const preserveStateRef = useRef(false)
  // Tracks the image.id we last processed in the reset effect.
  // Prevents React Strict Mode's double-invocation from running the reset twice.
  const lastProcessedIdRef = useRef<number | null>(null)

  const [editingName, setEditingName] = useState(false)
  const [editingSubgroup, setEditingSubgroup] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  // Reset UI state on image navigation (not on within-group variant click).
  // lastProcessedIdRef guards against React Strict Mode running this effect twice
  // for the same image.id — without it the second run would clear preserveStateRef
  // and reset scroll even on variant clicks.
  useEffect(() => {
    if (lastProcessedIdRef.current === image.id) return
    lastProcessedIdRef.current = image.id

    if (preserveStateRef.current) {
      preserveStateRef.current = false
      return
    }
    setEditingName(false)
    setEditingSubgroup(false)
    resetSceneFilters()
    if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0
  }, [image.id, resetSceneFilters])

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      // A dialog over the viewer (e.g. delete confirmation) owns the keyboard.
      if (editingName || editingSubgroup || isAnyDialogOpen()) return
      const target = e.target as HTMLElement
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'SELECT' ||
        target.tagName === 'TEXTAREA'
      )
        return
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') onNext?.()
      if (e.key === 'ArrowLeft') onPrevious?.()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose, onNext, onPrevious, editingName, editingSubgroup])

  const invalidateImage = () => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.image(image.id) })
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.scenes(image.id) })
  }

  const renameMutation = useMutation({
    mutationFn: (name: string) => imageApi.patch(image.id, { name }),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.image(image.id), updated)
      onImageChange?.(updated)
      setEditingName(false)
    },
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Failed to rename image'))
    },
  })

  const patchMutation = useMutation({
    mutationFn: (payload: ImagePatch) => imageApi.patch(image.id, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.image(image.id), updated)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.scenes() })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.search })
      onImageChange?.(updated)
    },
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Failed to update image'))
    },
  })

  const addTagMutation = useMutation({
    mutationFn: ({ category, value }: { category: string; value: string }) =>
      tagApi.addToImage(image.id, { category, value }),
    onSuccess: invalidateImage,
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Failed to add tag'))
    },
  })

  const removeTagMutation = useMutation({
    mutationFn: (tagId: number) => tagApi.removeTag(tagId),
    onSuccess: invalidateImage,
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Failed to remove tag'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => imageApi.delete(image.id),
    onSuccess: () => {
      invalidateGalleryQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.scenes() })
      setConfirmingDelete(false)

      // Navigate to the nearest sibling in the group (using pre-deletion scenes snapshot).
      // Only delegate to the parent onDelete when there are no siblings left — that's when
      // the parent needs to handle closing the viewer or moving to the next gallery item.
      const siblings = (scenes ?? []).filter((s) => s.id !== image.id)
      if (siblings.length > 0) {
        const deletedIdx = (scenes ?? []).findIndex((s) => s.id === image.id)
        const nextIdx = Math.min(Math.max(deletedIdx, 0), siblings.length - 1)
        preserveStateRef.current = true
        onImageChange?.(siblings[nextIdx])
      } else {
        onDelete?.(image.id)
      }
    },
  })

  const img = displayImage ?? image

  const handleSceneClick = (scene: Image) => {
    preserveStateRef.current = true
    onImageChange?.(scene)
  }

  return createPortal(
    <div
      data-testid="image-viewer"
      className="fixed inset-0 z-50 flex items-center justify-center lg:p-8"
      style={{ background: 'hsl(var(--background) / 0.88)' }}
      onClick={onClose}
    >
      <div
        ref={viewerRef}
        role="dialog"
        aria-modal="true"
        aria-label={img.name}
        tabIndex={-1}
        // Below lg the viewer fills the screen and stacks: image above, details below.
        className="relative flex flex-col lg:flex-row w-full h-full lg:h-[88vh] max-w-[1600px] lg:rounded-xl overflow-hidden lg:border border-border/20 shadow-2xl shadow-black/70 focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <ViewerStage image={img} onPrevious={onPrevious} onNext={onNext} />

        <div className="flex-1 min-h-0 overflow-y-auto lg:flex-none lg:w-[440px] lg:overflow-hidden flex flex-col border-t lg:border-t-0 lg:border-l border-border/20 bg-card">
          {/* Amber stripe — sidebar half: full at join, transparent at right edge */}
          <div className="h-0.5 shrink-0 bg-gradient-to-l from-transparent to-primary/80" />

          {/* Fixed: stays visible while the scenes below scroll */}
          <div className="px-4 pt-3 pb-2 shrink-0 border-b border-border/30">
            <ViewerToolbar
              image={img}
              onEditGroup={onEditGroup}
              onDelete={() => setConfirmingDelete(true)}
              onClose={onClose}
            />

            {img.group_name && img.group_name !== img.name && (
              <p className="font-display text-2xl font-semibold text-muted-foreground truncate mb-0.5">
                {img.group_name}
              </p>
            )}

            <ImageNameEditor
              name={img.name}
              editing={editingName}
              onEditingChange={setEditingName}
              onRename={(name) => renameMutation.mutate(name)}
            />

            <p className="text-sm text-muted-foreground">by {img.author}</p>

            <p
              className="text-[10px] text-muted-foreground font-mono truncate mt-1"
              title={img.filename}
            >
              {filenameStem(img.filename)}
            </p>
            <p className="text-[10px] text-muted-foreground mb-3">
              {img.width}×{img.height} · {(img.file_size / 1024 / 1024).toFixed(1)} MB
            </p>

            <ImageProperties
              image={img}
              existingSubgroups={sceneFilters.subgroups}
              editingSubgroup={editingSubgroup}
              onEditingSubgroupChange={setEditingSubgroup}
              onPatch={(patch) => patchMutation.mutate(patch)}
              patching={patchMutation.isPending}
            />

            <ImageTags
              image={img}
              onAddTag={(tag) =>
                addTagMutation.mutate({ category: tag.category, value: tag.value })
              }
              onRemoveTag={(tagId) => removeTagMutation.mutate(tagId)}
              removing={removeTagMutation.isPending}
            />
          </div>

          {scenes && scenes.length > 1 && (
            <ScenePanel
              scenes={scenes}
              sceneFilters={sceneFilters}
              activeImageId={img.id}
              onSceneClick={handleSceneClick}
              scrollRef={scrollContainerRef}
            />
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title="Delete Image"
        description={
          <>
            Permanently delete <strong>{img.name}</strong>? This cannot be undone.
          </>
        }
        confirmLabel="Delete"
        onConfirm={() => deleteMutation.mutate()}
        isLoading={deleteMutation.isPending}
      />
    </div>,
    document.body,
  )
}
