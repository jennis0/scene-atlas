import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { useGalleryDialogs } from './useGalleryDialogs'
import type { Image } from '@/types'

// ---------------------------------------------------------------------------
// Mock groupApi so we don't make real HTTP calls
// ---------------------------------------------------------------------------

vi.mock('@/lib/api', () => ({
  groupApi: {
    delete: vi.fn(),
  },
}))

import { groupApi } from '@/lib/api'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeImage(overrides: Partial<Image> = {}): Image {
  return {
    id: 1,
    storage_key: 'key-1',
    filename: 'forest.jpg',
    author: 'Author A',
    name: 'Forest Map',
    group_id: null,
    group_name: null,
    group_image_count: null,
    created_at: '2025-01-15T10:00:00Z',
    updated_at: '2025-01-15T10:00:00Z',
    file_size: 1024,
    width: 1920,
    height: 1080,
    gridded: null,
    grid_width: null,
    grid_height: null,
    grid_type: null,
    grid_confidence: null,
    subgroup: null,
    image_type: 'battlemap',
    thumbnail_key: null,
    media_type: 'image',
    tags: [],
    colors: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Wrapper with QueryClientProvider
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children)
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useGalleryDialogs — handleNext / handlePrevious', () => {
  const images = [
    makeImage({ id: 1, name: 'Image 1' }),
    makeImage({ id: 2, name: 'Image 2' }),
    makeImage({ id: 3, name: 'Image 3' }),
  ]

  it('handleNext advances to the next image', () => {
    const { result } = renderHook(() => useGalleryDialogs(images), {
      wrapper: createWrapper(),
    })

    // Select the first image
    act(() => {
      result.current.setSelectedImage({ image: images[0], index: 0 })
    })

    expect(result.current.selectedImage?.index).toBe(0)

    act(() => {
      result.current.handleNext()
    })

    expect(result.current.selectedImage?.index).toBe(1)
    expect(result.current.selectedImage?.image.id).toBe(2)
  })

  it('handlePrevious goes to the previous image', () => {
    const { result } = renderHook(() => useGalleryDialogs(images), {
      wrapper: createWrapper(),
    })

    // Select the last image
    act(() => {
      result.current.setSelectedImage({ image: images[2], index: 2 })
    })

    act(() => {
      result.current.handlePrevious()
    })

    expect(result.current.selectedImage?.index).toBe(1)
    expect(result.current.selectedImage?.image.id).toBe(2)
  })

  it('handleNext does not advance past the last image', () => {
    const { result } = renderHook(() => useGalleryDialogs(images), {
      wrapper: createWrapper(),
    })

    // Select the last image
    act(() => {
      result.current.setSelectedImage({ image: images[2], index: 2 })
    })

    act(() => {
      result.current.handleNext()
    })

    // Should stay at index 2
    expect(result.current.selectedImage?.index).toBe(2)
  })

  it('handlePrevious does not go below index 0', () => {
    const { result } = renderHook(() => useGalleryDialogs(images), {
      wrapper: createWrapper(),
    })

    // Select the first image
    act(() => {
      result.current.setSelectedImage({ image: images[0], index: 0 })
    })

    act(() => {
      result.current.handlePrevious()
    })

    // Should stay at index 0
    expect(result.current.selectedImage?.index).toBe(0)
  })

  it('handleNext does nothing when no image is selected', () => {
    const { result } = renderHook(() => useGalleryDialogs(images), {
      wrapper: createWrapper(),
    })

    expect(result.current.selectedImage).toBeNull()

    act(() => {
      result.current.handleNext()
    })

    expect(result.current.selectedImage).toBeNull()
  })
})

describe('useGalleryDialogs — openImportDialog', () => {
  it('increments key and sets jobId to "new" by default', () => {
    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    const initialKey = result.current.importDialogKey

    act(() => {
      result.current.openImportDialog()
    })

    expect(result.current.importDialogKey).toBe(initialKey + 1)
    expect(result.current.importDialogJobId).toBe('new')
  })

  it('increments key and sets specific jobId when provided', () => {
    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    const initialKey = result.current.importDialogKey

    act(() => {
      result.current.openImportDialog('job-123')
    })

    expect(result.current.importDialogKey).toBe(initialKey + 1)
    expect(result.current.importDialogJobId).toBe('job-123')
  })

  it('increments key each time it is called', () => {
    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    const initialKey = result.current.importDialogKey

    act(() => {
      result.current.openImportDialog()
    })
    act(() => {
      result.current.openImportDialog()
    })
    act(() => {
      result.current.openImportDialog()
    })

    expect(result.current.importDialogKey).toBe(initialKey + 3)
  })

  it('skips key increment when reopening the same mounted job', () => {
    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    // Simulate ImportDialog reporting its internal jobId
    act(() => {
      result.current.setMountedImportJob('job-456')
    })

    const keyBefore = result.current.importDialogKey

    // Reopen the same job — should NOT increment key
    act(() => {
      result.current.openImportDialog('job-456')
    })

    expect(result.current.importDialogKey).toBe(keyBefore)
    expect(result.current.importDialogJobId).toBe('job-456')
  })

  it('increments key when opening a different job than the mounted one', () => {
    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    act(() => {
      result.current.setMountedImportJob('job-456')
    })

    const keyBefore = result.current.importDialogKey

    // Open a different job — should increment key
    act(() => {
      result.current.openImportDialog('job-789')
    })

    expect(result.current.importDialogKey).toBe(keyBefore + 1)
    expect(result.current.importDialogJobId).toBe('job-789')
  })

  it('always increments key for "new" imports even if a job is mounted', () => {
    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    act(() => {
      result.current.setMountedImportJob('job-456')
    })

    const keyBefore = result.current.importDialogKey

    act(() => {
      result.current.openImportDialog() // 'new'
    })

    expect(result.current.importDialogKey).toBe(keyBefore + 1)
    expect(result.current.importDialogJobId).toBe('new')
  })
})

describe('useGalleryDialogs — handleGroupDeleteConfirm', () => {
  it('calls groupApi.delete and clears deleteConfirmGroup on success', async () => {
    vi.mocked(groupApi.delete).mockResolvedValueOnce(undefined)

    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    // Set up a group to delete
    act(() => {
      result.current.setDeleteConfirmGroup({
        groupId: 42,
        baseName: 'Test Group',
        author: 'Author',
        heroImage: makeImage(),
        mosaicImages: [],
        totalScenes: 3,
        matchingCount: 3,
        bestScore: null,
        aggregatedTags: [],
      })
    })

    expect(result.current.deleteConfirmGroup).not.toBeNull()

    await act(async () => {
      await result.current.handleGroupDeleteConfirm()
    })

    expect(groupApi.delete).toHaveBeenCalledWith(42)
    expect(result.current.deleteConfirmGroup).toBeNull()
    expect(result.current.deleting).toBe(false)
  })

  it('does nothing when deleteConfirmGroup has no groupId', async () => {
    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    // Set a group with null groupId
    act(() => {
      result.current.setDeleteConfirmGroup({
        groupId: null,
        baseName: 'Ungrouped',
        author: 'Author',
        heroImage: makeImage(),
        mosaicImages: [],
        totalScenes: 1,
        matchingCount: 1,
        bestScore: null,
        aggregatedTags: [],
      })
    })

    await act(async () => {
      await result.current.handleGroupDeleteConfirm()
    })

    expect(groupApi.delete).not.toHaveBeenCalled()
  })

  it('handles API error gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(groupApi.delete).mockRejectedValueOnce(new Error('Network error'))

    const { result } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    act(() => {
      result.current.setDeleteConfirmGroup({
        groupId: 42,
        baseName: 'Test Group',
        author: 'Author',
        heroImage: makeImage(),
        mosaicImages: [],
        totalScenes: 3,
        matchingCount: 3,
        bestScore: null,
        aggregatedTags: [],
      })
    })

    await act(async () => {
      await result.current.handleGroupDeleteConfirm()
    })

    expect(consoleSpy).toHaveBeenCalledWith('Failed to delete group:', expect.any(Error))
    expect(result.current.deleting).toBe(false)
    // Group is NOT cleared on error — user can retry
    expect(result.current.deleteConfirmGroup).not.toBeNull()

    consoleSpy.mockRestore()
  })
})

describe('useGalleryDialogs — invalidateGallery', () => {
  it('is a stable callback reference', () => {
    const { result, rerender } = renderHook(() => useGalleryDialogs([]), {
      wrapper: createWrapper(),
    })

    const ref1 = result.current.invalidateGallery
    rerender()
    const ref2 = result.current.invalidateGallery

    expect(ref1).toBe(ref2)
  })
})
