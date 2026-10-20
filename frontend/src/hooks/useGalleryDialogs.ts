import { useState, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { groupApi, imageApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { QUERY_KEYS, invalidateGalleryQueries } from '@/lib/queryKeys'
import type { Image, ImageGroup, SeedImage } from '@/types'

export interface UseGalleryDialogsReturn {
  // Image viewer
  selectedImage: { image: Image; index: number } | null
  setSelectedImage: React.Dispatch<React.SetStateAction<{ image: Image; index: number } | null>>
  handleNext: () => void
  handlePrevious: () => void

  // Edit group dialog
  editGroupId: number | null
  setEditGroupId: (id: number | null) => void

  // Group editor over every group an import created (from the import report)
  reviewGroupIds: number[] | null
  /** The group the editor opens on; otherwise it starts on all groups */
  reviewStartGroupId: number | undefined
  /** The import the groups came from, while the editor can follow it */
  reviewJobId: string | undefined
  setReviewGroupIds: (ids: number[] | null, startGroupId?: number, jobId?: string) => void
  /** Add groups to the open review (an import that's still running finished more) */
  addReviewGroupIds: (ids: number[]) => void

  // Mass edit dialog
  showMassEdit: boolean
  setShowMassEdit: (show: boolean) => void

  // Delete group confirmation
  deleteConfirmGroup: ImageGroup | null
  setDeleteConfirmGroup: (group: ImageGroup | null) => void
  handleGroupDeleteConfirm: () => Promise<void>
  deleting: boolean

  // Merge group picker
  mergeSourceGroup: ImageGroup | null
  setMergeSourceGroup: (group: ImageGroup | null) => void

  // Image actions from the individual view's tile menu
  moveImage: Image | null
  setMoveImage: (image: Image | null) => void
  deleteConfirmImage: Image | null
  setDeleteConfirmImage: (image: Image | null) => void
  handleImageDeleteConfirm: () => Promise<void>

  // Import dialog: a new import (jobId null) or an existing one. All import
  // state lives in the ImportManager, so opening and closing is free.
  importDialog: { open: boolean; jobId: string | null }
  openImport: (jobId?: string | null) => void
  closeImport: () => void

  // Tag management dialog
  showTagManagement: boolean
  setShowTagManagement: (show: boolean) => void

  // System info dialog
  showSystemInfo: boolean
  setShowSystemInfo: (show: boolean) => void

  // Edit all (mass edit) seed images and loading state
  editAllSeedImages: SeedImage[]
  setEditAllSeedImages: (images: SeedImage[]) => void
  editAllLoading: boolean
  setEditAllLoading: (loading: boolean) => void

  // Query invalidation
  invalidateGallery: () => void
}

interface ReviewState {
  groupIds: number[]
  startGroupId?: number
  jobId?: string
}

export function useGalleryDialogs(displayImages: Image[]): UseGalleryDialogsReturn {
  const queryClient = useQueryClient()

  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)
  const [editGroupId, setEditGroupId] = useState<number | null>(null)
  const [review, setReview] = useState<ReviewState | null>(null)
  const setReviewGroupIds = useCallback(
    (ids: number[] | null, startGroupId?: number, jobId?: string) =>
      setReview(ids ? { groupIds: ids, startGroupId, jobId } : null),
    [],
  )
  const addReviewGroupIds = useCallback(
    (ids: number[]) =>
      setReview((prev) => (prev ? { ...prev, groupIds: [...prev.groupIds, ...ids] } : prev)),
    [],
  )
  const [showMassEdit, setShowMassEdit] = useState(false)
  const [editAllSeedImages, setEditAllSeedImages] = useState<SeedImage[]>([])
  const [editAllLoading, setEditAllLoading] = useState(false)
  const [deleteConfirmGroup, setDeleteConfirmGroup] = useState<ImageGroup | null>(null)
  const [mergeSourceGroup, setMergeSourceGroup] = useState<ImageGroup | null>(null)
  const [moveImage, setMoveImage] = useState<Image | null>(null)
  const [deleteConfirmImage, setDeleteConfirmImage] = useState<Image | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [importDialog, setImportDialog] = useState<{ open: boolean; jobId: string | null }>({
    open: false,
    jobId: null,
  })
  const [showTagManagement, setShowTagManagement] = useState(false)
  const [showSystemInfo, setShowSystemInfo] = useState(false)

  // Read through a ref so handleNext/handlePrevious stay stable across result changes.
  const displayImagesRef = useRef(displayImages)
  displayImagesRef.current = displayImages

  const invalidateGallery = useCallback(() => invalidateGalleryQueries(queryClient), [queryClient])

  const handleNext = useCallback(() => {
    setSelectedImage((prev) => {
      if (!prev || prev.index >= displayImagesRef.current.length - 1) return prev
      const nextIndex = prev.index + 1
      return { image: displayImagesRef.current[nextIndex], index: nextIndex }
    })
  }, [])

  const handlePrevious = useCallback(() => {
    setSelectedImage((prev) => {
      if (!prev || prev.index <= 0) return prev
      const prevIndex = prev.index - 1
      return { image: displayImagesRef.current[prevIndex], index: prevIndex }
    })
  }, [])

  const handleGroupDeleteConfirm = useCallback(async () => {
    if (!deleteConfirmGroup?.groupId) return
    setDeleting(true)
    try {
      await groupApi.delete(deleteConfirmGroup.groupId)
      setDeleteConfirmGroup(null)
      invalidateGallery()
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Failed to delete group'))
    } finally {
      setDeleting(false)
    }
  }, [deleteConfirmGroup, invalidateGallery])

  const handleImageDeleteConfirm = useCallback(async () => {
    if (!deleteConfirmImage) return
    setDeleting(true)
    try {
      await imageApi.delete(deleteConfirmImage.id)
      setDeleteConfirmImage(null)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.scenes() })
      invalidateGallery()
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Failed to delete image'))
    } finally {
      setDeleting(false)
    }
  }, [deleteConfirmImage, invalidateGallery, queryClient])

  const openImport = useCallback((jobId: string | null = null) => {
    setImportDialog({ open: true, jobId })
  }, [])

  const closeImport = useCallback(() => {
    setImportDialog((prev) => ({ ...prev, open: false }))
  }, [])

  return {
    selectedImage,
    setSelectedImage,
    handleNext,
    handlePrevious,
    editGroupId,
    setEditGroupId,
    reviewGroupIds: review?.groupIds ?? null,
    reviewStartGroupId: review?.startGroupId,
    reviewJobId: review?.jobId,
    setReviewGroupIds,
    addReviewGroupIds,
    showMassEdit,
    setShowMassEdit,
    editAllSeedImages,
    setEditAllSeedImages,
    editAllLoading,
    setEditAllLoading,
    deleteConfirmGroup,
    setDeleteConfirmGroup,
    handleGroupDeleteConfirm,
    deleting,
    mergeSourceGroup,
    setMergeSourceGroup,
    moveImage,
    setMoveImage,
    deleteConfirmImage,
    setDeleteConfirmImage,
    handleImageDeleteConfirm,
    importDialog,
    openImport,
    closeImport,
    showTagManagement,
    setShowTagManagement,
    showSystemInfo,
    setShowSystemInfo,
    invalidateGallery,
  }
}
