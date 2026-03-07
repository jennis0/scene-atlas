import { useState, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { groupApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
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

  // Live import review dialog (active or completed job)
  importLiveJobId: string | null
  setImportLiveJobId: (id: string | null) => void

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
  openImportDialog: (jobId?: string, options?: { noRemount?: boolean }) => void
  setMountedImportJob: (id: string | null) => void

  // Tag management dialog
  showTagManagement: boolean
  setShowTagManagement: (show: boolean) => void

  // System info dialog
  showSystemInfo: boolean
  setShowSystemInfo: (show: boolean) => void

  // Settings panel
  settingsOpen: boolean
  setSettingsOpen: (show: boolean) => void

  // Import summary dialog (failed/broken jobs)
  importSummaryJobId: string | null
  setImportSummaryJobId: (id: string | null) => void

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

  // Live import review dialog (active or completed job)
  const [importLiveJobId, setImportLiveJobId] = useState<string | null>(null)

  // Mass edit dialog
  const [showMassEdit, setShowMassEdit] = useState(false)

  // Edit all (mass edit) seed images and loading state
  const [editAllSeedImages, setEditAllSeedImages] = useState<SeedImage[]>([])
  const [editAllLoading, setEditAllLoading] = useState(false)

  // Group action menu state
  const [deleteConfirmGroup, setDeleteConfirmGroup] = useState<ImageGroup | null>(null)
  const [mergeSourceGroup, setMergeSourceGroup] = useState<ImageGroup | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Import dialog state: null = closed, 'new' = fresh import, '{jobId}' = reconnect
  const [importDialogJobId, setImportDialogJobId] = useState<string | null>(null)
  const [importDialogKey, setImportDialogKey] = useState(0)

  // Tracks the job ID of the currently mounted ImportDialog instance.
  // Persists even when dialog is hidden (importDialogJobId=null) so we can
  // re-show without remounting and destroying in-progress uploads.
  const mountedImportJobRef = useRef<string | null>(null)

  // Tag management dialog
  const [showTagManagement, setShowTagManagement] = useState(false)

  // System info dialog
  const [showSystemInfo, setShowSystemInfo] = useState(false)

  // Settings panel
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Import summary dialog (failed/broken jobs)
  const [importSummaryJobId, setImportSummaryJobId] = useState<string | null>(null)

  // Keep a stable reference to displayImages for navigation handlers
  const displayImagesRef = useRef(displayImages)
  displayImagesRef.current = displayImages

  const invalidateGallery = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.search })
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.searchFacets })
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

  const openImportDialog = useCallback((jobId?: string, options?: { noRemount?: boolean }) => {
    const target = jobId ?? 'new'
    if (target !== 'new' && target === mountedImportJobRef.current) {
      // Same job already mounted — just re-show without remounting.
      // This preserves in-progress uploads and other component state.
      setImportDialogJobId(target)
      return
    }
    // Caller can opt out of remounting (e.g. for uploading jobs where
    // upload state can't be restored from scratch).
    if (options?.noRemount) return
    setImportDialogKey((k) => k + 1)
    setImportDialogJobId(target)
  }, [])

  // Called by ImportDialog when its internal jobId changes (e.g. after init)
  const setMountedImportJob = useCallback((id: string | null) => {
    mountedImportJobRef.current = id
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

    // Live import review dialog
    importLiveJobId,
    setImportLiveJobId,

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

    // Import dialog
    importDialogJobId,
    setImportDialogJobId,
    importDialogKey,
    openImportDialog,
    setMountedImportJob,

    // Tag management dialog
    showTagManagement,
    setShowTagManagement,

    // System info dialog
    showSystemInfo,
    setShowSystemInfo,

    // Settings panel
    settingsOpen,
    setSettingsOpen,

    // Import summary dialog (failed/broken jobs)
    importSummaryJobId,
    setImportSummaryJobId,

    // Query invalidation
    invalidateGallery,
  }
}
