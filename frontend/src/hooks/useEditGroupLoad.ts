import { useState, useEffect, useCallback, useRef } from 'react'
import { groupApi, tagApi, imageApi, getThumbnailUrlById, getImageUrlById } from '@/lib/api'
import { getApiErrorMessage, isNotFoundError } from '@/lib/getErrorMessage'
import { parseTagVocabulary } from '@/components/import/types'
import { EMPTY_FILTER } from '@/components/import/fileFilter'
import type { FileFilter } from '@/components/import/fileFilter'
import { ALL_TAB } from '@/hooks/useFileEditing'
import type {
  EditableFileState,
  EditableGroupState,
  GroupDetail,
  Image,
  GroupEditRequest,
  ParsedTagVocab,
  SeedImage,
} from '@/types'

export function imageToEditable(img: Image, outOfScope = false): EditableFileState {
  return {
    relative_path: String(img.id),
    filename: img.filename,
    name: img.name || img.filename,
    tags: img.tags.map((t) => ({
      category: t.category,
      value: t.value,
      confidence: t.confidence,
      source: t.source,
    })),
    gridded: img.gridded ?? null,
    grid_width: img.grid_width ?? null,
    grid_height: img.grid_height ?? null,
    grid_type: img.grid_type ?? null,
    subgroup: img.subgroup ?? null,
    image_type: img.image_type ?? 'battlemap',
    media_type: img.media_type ?? 'image',
    excluded: false,
    outOfScope,
    previewUrl: getThumbnailUrlById(img.id),
    fullImageUrl: getImageUrlById(img.id),
  }
}

/**
 * A group from the API as editor state. `isOutOfScope` marks images that are in the
 * group but not in the user's selection (mass edit), shown but not edited.
 */
export function groupDetailToEditable(
  detail: GroupDetail,
  isOutOfScope?: (imageId: number) => boolean,
): EditableGroupState {
  return {
    id: String(detail.id),
    author: detail.author ?? '',
    group_name: detail.base_name,
    files: detail.images.map((img) => imageToEditable(img, isOutOfScope?.(img.id) ?? false)),
  }
}

/** The active tab after removing the group at `removedIdx`; `fallback` if it was the active one. */
export function tabAfterRemoval(tab: number, removedIdx: number, fallback: number): number {
  if (tab === ALL_TAB) return tab
  if (removedIdx < tab) return tab - 1
  if (removedIdx === tab) return fallback
  return tab
}

export function toImageEdit(f: EditableFileState): GroupEditRequest['images'][number] {
  return {
    id: Number(f.relative_path),
    name: f.name,
    tags: f.tags,
    gridded: f.gridded,
    grid_width: f.grid_width,
    grid_height: f.grid_height,
    grid_type: f.grid_type,
    subgroup: f.subgroup,
    image_type: f.image_type,
  }
}

export function buildPayload(group: EditableGroupState): GroupEditRequest {
  return {
    base_name: group.group_name,
    author: group.author || undefined,
    images: group.files.filter((f) => !f.excluded).map(toImageEdit),
    new_groups: [],
  }
}

/** Import review loads groups this many at a time, showing each batch as it lands. */
const REVIEW_BATCH_SIZE = 8

export interface UseEditGroupLoadOptions {
  open: boolean
  groupId?: number | null
  seedImages?: SeedImage[]
  groupIds?: number[]
  /** Import review: open on this group rather than on all groups */
  startGroupId?: number
  /** Called in addition to resetLoad() when the single-group load effect
   *  detects no group to load (gId === null). Use this to reset dialog-local
   *  state (saving, merging, DnD, etc.) that the hook doesn't own. */
  onResetDialogState?: () => void
  fileEditing: {
    setGroups: (
      groups: EditableGroupState[] | ((prev: EditableGroupState[]) => EditableGroupState[]),
    ) => void
    setActiveTab: (tab: number) => void
    setFileFilter: (filter: FileFilter) => void
    setEditingSvHeading: (v: string | null) => void
    setTagVocab: (v: ParsedTagVocab[] | ((prev: ParsedTagVocab[]) => ParsedTagVocab[])) => void
    setAuthorSuggestions: (v: string[] | ((prev: string[]) => string[])) => void
  }
}

export interface UseEditGroupLoadReturn {
  loading: boolean
  loadError: string | null
  isMassEdit: boolean
  ungroupedCount: number
  /** Import review: groups still loading after the editor opened */
  pendingGroupCount: number
  resetLoad: () => void
}

export function useEditGroupLoad({
  open,
  groupId,
  seedImages,
  groupIds,
  startGroupId,
  onResetDialogState,
  fileEditing,
}: UseEditGroupLoadOptions): UseEditGroupLoadReturn {
  // Read when the first batch lands; a ref so a new start group doesn't refetch
  const startGroupIdRef = useRef(startGroupId)
  startGroupIdRef.current = startGroupId
  const {
    setGroups,
    setActiveTab,
    setFileFilter,
    setEditingSvHeading,
    setTagVocab,
    setAuthorSuggestions,
  } = fileEditing

  const isMassEdit = !!seedImages && seedImages.length > 0
  const isImportReview = !!groupIds && groupIds.length > 0

  const [loading, setLoading] = useState(false)
  // Import review: groups still being fetched after the editor has opened
  const [pendingGroupCount, setPendingGroupCount] = useState(0)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [ungroupedCount, setUngroupedCount] = useState(0)

  // Tracks which group IDs have already been fetched in import-review mode;
  // reset when the dialog closes/reopens so incremental loads start fresh.
  const loadedGroupIdsRef = useRef(new Set<number>())

  // Read through a ref so a new callback identity doesn't re-run the load effects.
  const onResetDialogStateRef = useRef(onResetDialogState)
  onResetDialogStateRef.current = onResetDialogState

  const resetLoad = useCallback(() => {
    setLoading(false)
    setLoadError(null)
    setUngroupedCount(0)
    setGroups([])
    setActiveTab(0)
    setFileFilter(EMPTY_FILTER)
    setEditingSvHeading(null)
    loadedGroupIdsRef.current = new Set()
    setPendingGroupCount(0)
  }, [setGroups, setActiveTab, setFileFilter, setEditingSvHeading])

  // Start every opening fresh. Without this, import review kept the previous
  // review's groups and appended the next import's after them.
  useEffect(() => {
    if (open) return
    resetLoad()
    onResetDialogStateRef.current?.()
  }, [open, resetLoad])

  // Single-group mode
  useEffect(() => {
    if (!open || isMassEdit || isImportReview) return
    const gId = groupId ?? null
    if (gId === null) {
      resetLoad()
      onResetDialogStateRef.current?.()
      return
    }

    setLoading(true)
    setLoadError(null)
    // Ignore a response that lands after the dialog closed or switched group.
    let cancelled = false

    Promise.all([groupApi.get(gId), tagApi.getCategories(), imageApi.getAuthors()])
      .then(([group, categories, authors]) => {
        if (cancelled) return
        setGroups([groupDetailToEditable(group)])
        setTagVocab(parseTagVocabulary(categories))
        setAuthorSuggestions(authors)
        setActiveTab(0)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (isNotFoundError(err)) {
          setLoadError('This group no longer exists — it may have been merged or deleted.')
        } else {
          setLoadError(getApiErrorMessage(err, 'Failed to load group'))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [
    open,
    groupId,
    isMassEdit,
    isImportReview,
    resetLoad,
    setGroups,
    setTagVocab,
    setAuthorSuggestions,
    setActiveTab,
  ])

  // Mass-edit mode
  useEffect(() => {
    if (!open || !isMassEdit) return

    setLoading(true)
    setLoadError(null)

    const byGroup = new Map<number, SeedImage[]>()
    let ungrouped = 0
    for (const img of seedImages!) {
      if (img.group_id === null) {
        ungrouped++
      } else {
        const list = byGroup.get(img.group_id) ?? []
        list.push(img)
        byGroup.set(img.group_id, list)
      }
    }

    const groupIdKeys = [...byGroup.keys()]
    if (groupIdKeys.length === 0) {
      setLoadError('None of the search results belong to a variant group.')
      setLoading(false)
      return
    }

    setUngroupedCount(ungrouped)
    let cancelled = false

    Promise.all([
      ...groupIdKeys.map((id) => groupApi.get(id)),
      tagApi.getCategories(),
      imageApi.getAuthors(),
    ])
      .then((results) => {
        if (cancelled) return
        const groupDetails = results.slice(0, groupIdKeys.length) as GroupDetail[]
        const categories = results[groupIdKeys.length] as Awaited<
          ReturnType<typeof tagApi.getCategories>
        >
        const authors = results[groupIdKeys.length + 1] as string[]

        // Every image in each group is loaded; those not in the search results are out of scope.
        const editableGroups = groupDetails.map((detail) => {
          const seedIds = new Set((byGroup.get(detail.id) ?? []).map((img) => img.id))
          return groupDetailToEditable(detail, (id) => !seedIds.has(id))
        })

        setGroups(editableGroups)
        setTagVocab(parseTagVocabulary(categories))
        setAuthorSuggestions(authors)
        setActiveTab(editableGroups.length > 1 ? ALL_TAB : 0)
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(getApiErrorMessage(err, 'Failed to load groups'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [open, seedImages, isMassEdit, setGroups, setTagVocab, setAuthorSuggestions, setActiveTab])

  // Import-review mode: incremental, fetching only newly added IDs

  useEffect(() => {
    if (!open || !isImportReview) return

    const allIds = groupIds ?? []
    const newIds = allIds.filter((id) => !loadedGroupIdsRef.current.has(id))
    if (newIds.length === 0) return

    // isFirstLoad is captured synchronously before any async work; safe to use below
    const isFirstLoad = loadedGroupIdsRef.current.size === 0
    // Claim the ids now so a re-run while batches are in flight doesn't fetch them twice
    newIds.forEach((id) => loadedGroupIdsRef.current.add(id))

    // A group the user asked to start on is fetched first and goes first in the sidebar:
    // groups are appended as batches land, so it can't be slotted in later without
    // shifting the selection.
    const start = isFirstLoad ? startGroupIdRef.current : undefined
    const startFirst = start !== undefined && newIds.includes(start)
    const rest = startFirst ? newIds.filter((id) => id !== start) : newIds
    const batches: number[][] = startFirst ? [[start]] : []
    for (let i = 0; i < rest.length; i += REVIEW_BATCH_SIZE) {
      batches.push(rest.slice(i, i + REVIEW_BATCH_SIZE))
    }
    // Ids claimed above but not yet shown; released if this run is abandoned
    const unshown = new Set(newIds)

    if (isFirstLoad) {
      setLoading(true)
      setLoadError(null)
    }
    setPendingGroupCount((n) => n + newIds.length)

    // Cancellation flag — prevents stale responses from mutating state if the dialog
    // closes and reopens (resetting loadedGroupIdsRef) before this fetch resolves.
    let cancelled = false

    // Show the editor as soon as the first batch is in; later batches append. Vocab
    // and authors are global, so they're fetched once, with the first batch.
    const run = async () => {
      for (const [index, batch] of batches.entries()) {
        const first = isFirstLoad && index === 0
        const [details, categories, authors] = await Promise.all([
          Promise.all(batch.map((id) => groupApi.get(id))),
          first ? tagApi.getCategories() : undefined,
          first ? imageApi.getAuthors() : undefined,
        ])
        if (cancelled) return
        setGroups((prev) => [...prev, ...details.map((detail) => groupDetailToEditable(detail))])
        batch.forEach((id) => unshown.delete(id))
        setPendingGroupCount((n) => n - batch.length)
        if (first) {
          setTagVocab(parseTagVocabulary(categories!))
          setAuthorSuggestions(authors!)
          setActiveTab(startFirst ? 0 : allIds.length > 1 ? ALL_TAB : 0)
          setLoading(false)
        }
      }
    }
    run().catch((err: unknown) => {
      if (cancelled) return
      setPendingGroupCount((n) => n - unshown.size)
      setLoading(false)
      setLoadError(getApiErrorMessage(err, 'Failed to load imported groups'))
    })

    return () => {
      cancelled = true
      // Let a re-run fetch whatever this run hadn't shown yet
      unshown.forEach((id) => loadedGroupIdsRef.current.delete(id))
      setPendingGroupCount((n) => n - unshown.size)
    }
  }, [open, groupIds, isImportReview, setGroups, setTagVocab, setAuthorSuggestions, setActiveTab])

  return {
    loading,
    loadError,
    isMassEdit,
    ungroupedCount,
    pendingGroupCount,
    resetLoad,
  }
}
