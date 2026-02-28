import { useState, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { groupApi } from '@/lib/api'
import type { Image, ImageGroup } from '@/types'

// ---------------------------------------------------------------------------
// Return type
// ---------------------------------------------------------------------------

export interface UseGalleryDialogsReturn {
  // Image viewer
  selectedImage: { image: Image; index: number } | null
  setSelectedImage: React.Dispatch<React.SetStateAction<{ image: Image; index: number } | null>>
  handleNext: () => void
  handlePrevious: () => void

  // Edit group dialog
  editGroupId: number | null
  setEditGroupId: (id: number | null) => void

  // Import review dialog
  importReviewGroupIds: number[] | null
  setImportReviewGroupIds: (ids: number[] | null) => void

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

  // Import dialog
  importDialogJobId: string | null
  setImportDialogJobId: (id: string | null) => void
  importDialogKey: number
  openImportDialog: (jobId?: string) => void

  // Tag management dialog
  showTagManagement: boolean
  setShowTagManagement: (show: boolean) => void

  // System info dialog
  showSystemInfo: boolean
  setShowSystemInfo: (show: boolean) => void

  // Query invalidation
  invalidateGallery: () => void
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGalleryDialogs(displayImages: Image[]): UseGalleryDialogsReturn {
  const queryClient = useQueryClient()

  // Image viewer state
  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)

  // Edit group dialog
  const [editGroupId, setEditGroupId] = useState<number | null>(null)

  // Import review dialog
  const [importReviewGroupIds, setImportReviewGroupIds] = useState<number[] | null>(null)

  // Mass edit dialog
  const [showMassEdit, setShowMassEdit] = useState(false)

  // Group action menu state
  const [deleteConfirmGroup, setDeleteConfirmGroup] = useState<ImageGroup | null>(null)
  const [mergeSourceGroup, setMergeSourceGroup] = useState<ImageGroup | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Import dialog state: null = closed, 'new' = fresh import, '{jobId}' = reconnect
  const [importDialogJobId, setImportDialogJobId] = useState<string | null>(null)
  const [importDialogKey, setImportDialogKey] = useState(0)

  // Tag management dialog
  const [showTagManagement, setShowTagManagement] = useState(false)

  // System info dialog
  const [showSystemInfo, setShowSystemInfo] = useState(false)

  // Keep a stable reference to displayImages for navigation handlers
  const displayImagesRef = useRef(displayImages)
  displayImagesRef.current = displayImages

  const invalidateGallery = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['search'] })
    queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
  }, [queryClient])

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
      console.error('Failed to delete group:', err)
    } finally {
      setDeleting(false)
    }
  }, [deleteConfirmGroup, invalidateGallery])

  const openImportDialog = useCallback((jobId?: string) => {
    setImportDialogKey((k) => k + 1)
    setImportDialogJobId(jobId ?? 'new')
  }, [])

  return {
    // Image viewer
    selectedImage,
    setSelectedImage,
    handleNext,
    handlePrevious,

    // Edit group dialog
    editGroupId,
    setEditGroupId,

    // Import review dialog
    importReviewGroupIds,
    setImportReviewGroupIds,

    // Mass edit dialog
    showMassEdit,
    setShowMassEdit,

    // Delete group confirmation
    deleteConfirmGroup,
    setDeleteConfirmGroup,
    handleGroupDeleteConfirm,
    deleting,

    // Merge group picker
    mergeSourceGroup,
    setMergeSourceGroup,

    // Import dialog
    importDialogJobId,
    setImportDialogJobId,
    importDialogKey,
    openImportDialog,

    // Tag management dialog
    showTagManagement,
    setShowTagManagement,

    // System info dialog
    showSystemInfo,
    setShowSystemInfo,

    // Query invalidation
    invalidateGallery,
  }
}
