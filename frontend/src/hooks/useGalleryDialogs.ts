import { useState, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { groupApi } from '@/lib/api'
import { invalidateGalleryQueries } from '@/lib/queryKeys'
import type { Image, ImageGroup, SeedImage } from '@/types'

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

  // Group editor over every group an import created (from the import report)
  reviewGroupIds: number[] | null
  setReviewGroupIds: (ids: number[] | null) => void

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

  // Import dialog: a new import (jobId null) or an existing one. All import
  // state lives in the ImportManager, so opening and closing is free.
  importDialog: { open: boolean; jobId: string | null }
  openImport: (jobId?: string | null) => void
  closeImport: () => void

  // Import report
  reportJobId: string | null
  setReportJobId: (id: string | null) => void

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

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGalleryDialogs(displayImages: Image[]): UseGalleryDialogsReturn {
  const queryClient = useQueryClient()

  // Image viewer state
  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)

  // Edit group dialog
  const [editGroupId, setEditGroupId] = useState<number | null>(null)

  // Group editor over an import's groups
  const [reviewGroupIds, setReviewGroupIds] = useState<number[] | null>(null)

  // Mass edit dialog
  const [showMassEdit, setShowMassEdit] = useState(false)

  // Edit all (mass edit) seed images and loading state
  const [editAllSeedImages, setEditAllSeedImages] = useState<SeedImage[]>([])
  const [editAllLoading, setEditAllLoading] = useState(false)

  // Group action menu state
  const [deleteConfirmGroup, setDeleteConfirmGroup] = useState<ImageGroup | null>(null)
  const [mergeSourceGroup, setMergeSourceGroup] = useState<ImageGroup | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Import dialog and report
  const [importDialog, setImportDialog] = useState<{ open: boolean; jobId: string | null }>({
    open: false,
    jobId: null,
  })
  const [reportJobId, setReportJobId] = useState<string | null>(null)

  // Tag management dialog
  const [showTagManagement, setShowTagManagement] = useState(false)

  // System info dialog
  const [showSystemInfo, setShowSystemInfo] = useState(false)

  // Keep a stable reference to displayImages for navigation handlers
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
      console.error('Failed to delete group:', err)
    } finally {
      setDeleting(false)
    }
  }, [deleteConfirmGroup, invalidateGallery])

  const openImport = useCallback((jobId: string | null = null) => {
    setImportDialog({ open: true, jobId })
  }, [])

  const closeImport = useCallback(() => {
    setImportDialog((prev) => ({ ...prev, open: false }))
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

    // Group editor over an import's groups
    reviewGroupIds,
    setReviewGroupIds,

    // Mass edit dialog
    showMassEdit,
    setShowMassEdit,

    // Edit all (mass edit) seed images and loading state
    editAllSeedImages,
    setEditAllSeedImages,
    editAllLoading,
    setEditAllLoading,

    // Delete group confirmation
    deleteConfirmGroup,
    setDeleteConfirmGroup,
    handleGroupDeleteConfirm,
    deleting,

    // Merge group picker
    mergeSourceGroup,
    setMergeSourceGroup,

    // Import dialog and report
    importDialog,
    openImport,
    closeImport,
    reportJobId,
    setReportJobId,

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
