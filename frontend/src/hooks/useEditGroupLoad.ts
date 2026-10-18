import { useState, useEffect, useCallback, useRef, type MutableRefObject } from 'react'
import { groupApi, tagApi, imageApi, getThumbnailUrlById, getImageUrlById } from '@/lib/api'
import { toast } from 'sonner'
import { getApiErrorMessage, isNotFoundError } from '@/lib/getErrorMessage'
import { serverId } from '@/lib/serverId'
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
  GroupSummary,
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

/** Ids of the files marked for deletion. Deletion is explicit: unlisted images are kept,
 * so images imported into the group after it loaded are never deleted. */
export function deletedImageIds(files: EditableFileState[]): number[] {
  return files
    .filter((f) => f.excluded)
    .map((f) => serverId(f.relative_path))
    .filter((id) => id !== null)
}

export function buildPayload(group: EditableGroupState): GroupEditRequest {
  return {
    base_name: group.group_name,
    author: group.author || undefined,
    images: group.files.filter((f) => !f.excluded).map(toImageEdit),
    new_groups: [],
    delete_image_ids: deletedImageIds(group.files),
  }
}

/**
 * Import review shows a small first batch quickly, then appends bigger ones: every
 * append re-renders the whole editor (each file card), so that cost, not the
 * requests, is what limits how fast a large import fills in.
 */
const REVIEW_FIRST_BATCH = 8
const REVIEW_BATCH_SIZE = 40

/**
 * Above this many images, import review opens on the first group rather than on All:
 * All renders every file card, which makes a very large import slow to open.
 */
export const ALL_VIEW_IMAGE_LIMIT = 500

/**
 * Above this many images, import review is in large mode: only the summaries load up
 * front, a group's files load when it's opened, and All is a bulk panel rather than a
 * file grid (see design/editor-metadata-first.md, phase 4).
 */
export const LARGE_REVIEW_IMAGES = 5000

/**
 * The next group ids to fetch from `queue`. A group the user is waiting on (the start
 * group, or a placeholder they clicked) goes alone and first; otherwise a small batch
 * until something is on screen, then large ones.
 */
export function nextReviewBatch(
  queue: number[],
  priority: number | null,
  shownAny: boolean,
): number[] {
  if (priority !== null && queue.includes(priority)) return [priority]
  return queue.slice(0, shownAny ? REVIEW_BATCH_SIZE : REVIEW_FIRST_BATCH)
}

/** The tab import review opens on, once its first groups have arrived. */
export function initialReviewTab(summaries: GroupSummary[], startFirst: boolean): number {
  if (startFirst || summaries.length < 2) return 0
  const images = summaries.reduce((n, g) => n + g.image_count, 0)
  return images > ALL_VIEW_IMAGE_LIMIT ? 0 : ALL_TAB
}

type OnReviewBatch = (details: GroupDetail[], batch: number[], first: boolean) => void

/**
 * Fetch the queued groups' details batch by batch (see nextReviewBatch), handing each
 * batch to `onBatch` as it lands. Stops early once `isCancelled` says so.
 */
async function drainReviewQueue(
  ids: number[],
  priorityRef: MutableRefObject<number | null>,
  isCancelled: () => boolean,
  onBatch: OnReviewBatch,
): Promise<void> {
  let queue = ids
  let first = true
  while (queue.length > 0) {
    const batch = nextReviewBatch(queue, priorityRef.current, !first)
    const details = await groupApi.details(batch)
    if (isCancelled()) return
    const done = new Set(batch)
    queue = queue.filter((id) => !done.has(id))
    if (priorityRef.current !== null && done.has(priorityRef.current)) priorityRef.current = null
    onBatch(details, batch, first)
    first = false
  }
}

/** True when an import is big enough for large-mode review (LARGE_REVIEW_IMAGES). */
function isLargeImport(summaries: GroupSummary[]) {
  return summaries.reduce((n, g) => n + g.image_count, 0) > LARGE_REVIEW_IMAGES
}

/** `order` with the ids of `summaries` it doesn't have yet appended. */
function withNewIds(order: number[], summaries: GroupSummary[]) {
  const known = new Set(order)
  return [...order, ...summaries.map((g) => g.id).filter((id) => !known.has(id))]
}

interface QueueOptions {
  large: boolean
  firstLoad: boolean
  priority: number | null
}

/**
 * The groups import review fetches up front: all of them normally; in large mode only
 * the one it opens on (the start group, else the first), and only on the first load.
 */
function reviewQueue(summaries: GroupSummary[], { large, firstLoad, priority }: QueueOptions) {
  if (!large) return summaries.map((g) => g.id)
  const first = priority ?? summaries[0]?.id
  if (!firstLoad || first === undefined) return []
  return [first]
}

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
    groups: EditableGroupState[]
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
  /** Import review: groups listed but still loading, in sidebar order */
  pendingGroups: GroupSummary[]
  /** Fetch this pending group next, and open it when it arrives */
  prioritizeGroup: (groupId: number) => void
  /** Large mode: files load per group when opened, and All is the bulk panel */
  isLargeReview: boolean
  /** Import review: every listed group's id in sidebar order, loaded or not */
  groupOrder: number[]
  /** The pending group the user clicked and is waiting on */
  awaitedGroupId: number | null
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
    groups,
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
  // Import review: groups summarised (so listed) but whose files are still being fetched
  const [pendingGroups, setPendingGroups] = useState<GroupSummary[]>([])
  // The group to fetch next and then open: the start group, or a placeholder clicked
  const priorityRef = useRef<number | null>(null)
  const [openWhenLoaded, setOpenWhenLoaded] = useState<number | null>(null)
  const [groupOrder, setGroupOrder] = useState<number[]>([])
  const [isLargeReview, setIsLargeReview] = useState(false)
  const largeRef = useRef(false)
  // Large mode: groups being fetched on demand, and a generation that drops responses
  // landing after the dialog was reset
  const fetchingRef = useRef(new Set<number>())
  const generationRef = useRef(0)
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
    setPendingGroups([])
    priorityRef.current = null
    setOpenWhenLoaded(null)
    setGroupOrder([])
    setIsLargeReview(false)
    largeRef.current = false
    fetchingRef.current = new Set()
    generationRef.current++
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

    Promise.all([groupApi.details(groupIdKeys), tagApi.getCategories(), imageApi.getAuthors()])
      .then(([groupDetails, categories, authors]) => {
        if (cancelled) return

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

  // Import-review mode: incremental, fetching only newly added IDs. Summaries come
  // first, so every group is listed at once; files follow in batches.
  useEffect(() => {
    if (!open || !isImportReview) return

    const allIds = groupIds ?? []
    const newIds = allIds.filter((id) => !loadedGroupIdsRef.current.has(id))
    if (newIds.length === 0) return

    // isFirstLoad is captured synchronously before any async work; safe to use below
    const isFirstLoad = loadedGroupIdsRef.current.size === 0
    // Claim the ids now so a re-run while batches are in flight doesn't fetch them twice
    newIds.forEach((id) => loadedGroupIdsRef.current.add(id))
    // Ids claimed above but not yet shown; released if this run is abandoned
    const unshown = new Set(newIds)

    if (isFirstLoad) {
      setLoading(true)
      setLoadError(null)
      const start = startGroupIdRef.current
      if (start !== undefined && newIds.includes(start)) priorityRef.current = start
    }

    // Cancellation flag — prevents stale responses from mutating state if the dialog
    // closes and reopens (resetting loadedGroupIdsRef) before this fetch resolves.
    let cancelled = false

    // Vocab and authors are global, so they're fetched once, with the summaries.
    const run = async () => {
      const [summaries, categories, authors] = await Promise.all([
        groupApi.summaries(newIds),
        isFirstLoad ? tagApi.getCategories() : undefined,
        isFirstLoad ? imageApi.getAuthors() : undefined,
      ])
      if (cancelled) return
      const listed = new Set(summaries.map((g) => g.id))
      // Groups gone since the import (merged or deleted) are simply not listed
      newIds.filter((id) => !listed.has(id)).forEach((id) => unshown.delete(id))
      setPendingGroups((prev) => [...prev.filter((g) => !listed.has(g.id)), ...summaries])
      setGroupOrder((prev) => withNewIds(prev, summaries))
      const startFirst = priorityRef.current !== null && listed.has(priorityRef.current)
      if (isFirstLoad && isLargeImport(summaries)) {
        largeRef.current = true
        setIsLargeReview(true)
      }
      // Large mode: listed is shown; the rest load when opened, not on a re-run
      if (largeRef.current) summaries.forEach((g) => unshown.delete(g.id))
      const queue = reviewQueue(summaries, {
        large: largeRef.current,
        firstLoad: isFirstLoad,
        priority: priorityRef.current,
      })

      await drainReviewQueue(
        queue,
        priorityRef,
        () => cancelled,
        (details, batch, first) => {
          setGroups((prev) => [...prev, ...details.map((detail) => groupDetailToEditable(detail))])
          const done = new Set(batch)
          setPendingGroups((prev) => prev.filter((g) => !done.has(g.id)))
          batch.forEach((id) => unshown.delete(id))
          if (!isFirstLoad || !first) return
          setTagVocab(parseTagVocabulary(categories!))
          setAuthorSuggestions(authors!)
          setActiveTab(initialReviewTab(summaries, startFirst))
          setLoading(false)
        },
      )
    }
    run()
      .then(() => {
        if (!cancelled && isFirstLoad) setLoading(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setPendingGroups([])
        setLoading(false)
        setLoadError(getApiErrorMessage(err, 'Failed to load imported groups'))
      })

    return () => {
      cancelled = true
      // Let a re-run fetch whatever this run hadn't shown yet. Its placeholders stay
      // listed; the re-run's summaries replace them.
      unshown.forEach((id) => loadedGroupIdsRef.current.delete(id))
    }
  }, [open, groupIds, isImportReview, setGroups, setTagVocab, setAuthorSuggestions, setActiveTab])

  // Large mode: a placeholder the user clicked loads now (one request for its files).
  useEffect(() => {
    const id = openWhenLoaded
    if (!isLargeReview || id === null || fetchingRef.current.has(id)) return
    if (groups.some((g) => g.id === String(id))) return
    fetchingRef.current.add(id)
    const generation = generationRef.current
    groupApi
      .details([id])
      .then(([detail]) => {
        if (generation !== generationRef.current) return
        if (detail) setGroups((prev) => [...prev, groupDetailToEditable(detail)])
        else setOpenWhenLoaded(null)
        setPendingGroups((prev) => prev.filter((g) => g.id !== id))
      })
      .catch((err: unknown) => {
        if (generation !== generationRef.current) return
        setOpenWhenLoaded(null)
        toast.error(getApiErrorMessage(err, 'Failed to load the group'))
      })
      .finally(() => fetchingRef.current.delete(id))
  }, [isLargeReview, openWhenLoaded, groups, setGroups])

  // A placeholder the user clicked has arrived: open it.
  useEffect(() => {
    if (openWhenLoaded === null) return
    const index = groups.findIndex((g) => g.id === String(openWhenLoaded))
    if (index === -1) return
    setActiveTab(index)
    setOpenWhenLoaded(null)
  }, [openWhenLoaded, groups, setActiveTab])

  const prioritizeGroup = useCallback((groupId: number) => {
    priorityRef.current = groupId
    setOpenWhenLoaded(groupId)
  }, [])

  return {
    loading,
    loadError,
    isMassEdit,
    ungroupedCount,
    pendingGroups,
    prioritizeGroup,
    awaitedGroupId: openWhenLoaded,
    isLargeReview,
    groupOrder,
    resetLoad,
  }
}
