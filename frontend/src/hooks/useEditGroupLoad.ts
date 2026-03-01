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
  Image,
  GroupEditRequest,
  ParsedTagVocab,
} from '@/types'

// ── Pure helpers (exported for use by EditGroupDialog) ────────────────────

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
    excluded: false,
    outOfScope,
    previewUrl: getThumbnailUrlById(img.id),
    fullImageUrl: getImageUrlById(img.id),
  }
}

export function buildPayload(group: EditableGroupState): GroupEditRequest {
  const kept = group.files.filter((f) => !f.excluded)
  return {
    base_name: group.group_name,
    author: group.author || undefined,
    images: kept.map((f) => ({
      id: Number(f.relative_path),
      name: f.name,
      tags: f.tags,
      gridded: f.gridded,
      grid_width: f.grid_width,
      grid_height: f.grid_height,
      grid_type: f.grid_type,
      subgroup: f.subgroup,
      image_type: f.image_type,
    })),
    new_groups: [],
  }
}

// ── Hook options ──────────────────────────────────────────────────────────

export interface UseEditGroupLoadOptions {
  open: boolean
  groupId?: number | null
  seedImages?: Image[]
  groupIds?: number[]
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
  isImportReview: boolean
  ungroupedCount: number
  resetLoad: () => void
}

// ── Hook ──────────────────────────────────────────────────────────────────

export function useEditGroupLoad({
  open,
  groupId,
  seedImages,
  groupIds,
  onResetDialogState,
  fileEditing,
}: UseEditGroupLoadOptions): UseEditGroupLoadReturn {
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
  const [loadError, setLoadError] = useState<string | null>(null)
  const [ungroupedCount, setUngroupedCount] = useState(0)

  // Ref to avoid stale closure in effects — always points to latest callback
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
  }, [setGroups, setActiveTab, setFileFilter, setEditingSvHeading])

  // ── Load: single-group mode ──────────────────────────────────────

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

    Promise.all([groupApi.get(gId), tagApi.getCategories(), imageApi.getAuthors()])
      .then(([group, categories, authors]) => {
        setGroups([
          {
            id: String(group.id),
            author: group.author ?? '',
            group_name: group.base_name,
            files: group.images.map((img) => imageToEditable(img)),
            skip: false,
            status: 'pending',
            processed: 0,
            failed: 0,
            total: group.images.length,
          },
        ])
        setTagVocab(parseTagVocabulary(categories))
        setAuthorSuggestions(authors)
        setActiveTab(0)
      })
      .catch((err: unknown) => {
        if (isNotFoundError(err)) {
          setLoadError('This group no longer exists — it may have been merged or deleted.')
        } else {
          setLoadError(getApiErrorMessage(err, 'Failed to load group'))
        }
      })
      .finally(() => {
        setLoading(false)
      })
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

  // ── Load: mass-edit mode ─────────────────────────────────────────

  useEffect(() => {
    if (!open || !isMassEdit) return

    setLoading(true)
    setLoadError(null)

    // Group seed images by group_id
    const byGroup = new Map<number, Image[]>()
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

    Promise.all([
      ...groupIdKeys.map((id) => groupApi.get(id)),
      tagApi.getCategories(),
      imageApi.getAuthors(),
    ])
      .then((results) => {
        const groupDetails = results.slice(0, groupIdKeys.length) as Awaited<
          ReturnType<typeof groupApi.get>
        >[]
        const categories = results[groupIdKeys.length] as Awaited<
          ReturnType<typeof tagApi.getCategories>
        >
        const authors = results[groupIdKeys.length + 1] as string[]

        const editableGroups: EditableGroupState[] = groupDetails.map((detail) => {
          const seedIds = new Set((byGroup.get(detail.id) ?? []).map((img) => img.id))
          return {
            id: String(detail.id),
            author: detail.author ?? '',
            group_name: detail.base_name,
            // ALL images in the group; non-seed ones marked outOfScope
            files: detail.images.map((img) => imageToEditable(img, !seedIds.has(img.id))),
            skip: false,
            status: 'pending',
            processed: 0,
            failed: 0,
            total: detail.images.length,
          }
        })

        setGroups(editableGroups)
        setTagVocab(parseTagVocabulary(categories))
        setAuthorSuggestions(authors)
        setActiveTab(editableGroups.length > 1 ? ALL_TAB : 0)
      })
      .catch((err: unknown) => {
        setLoadError(getApiErrorMessage(err, 'Failed to load groups'))
      })
      .finally(() => {
        setLoading(false)
      })
  }, [
    open,
    seedImages,
    isMassEdit,
    resetLoad,
    setGroups,
    setTagVocab,
    setAuthorSuggestions,
    setActiveTab,
  ])

  // ── Load: import-review mode (multiple groups by ID, all images in scope) ──

  useEffect(() => {
    if (!open || !isImportReview) return

    setLoading(true)
    setLoadError(null)

    const ids = groupIds!
    Promise.all([
      ...ids.map((id) => groupApi.get(id)),
      tagApi.getCategories(),
      imageApi.getAuthors(),
    ])
      .then((results) => {
        const groupDetails = results.slice(0, ids.length) as Awaited<
          ReturnType<typeof groupApi.get>
        >[]
        const categories = results[ids.length] as Awaited<ReturnType<typeof tagApi.getCategories>>
        const authors = results[ids.length + 1] as string[]

        const editableGroups: EditableGroupState[] = groupDetails.map((detail) => ({
          id: String(detail.id),
          author: detail.author ?? '',
          group_name: detail.base_name,
          files: detail.images.map((img) => imageToEditable(img)),
          skip: false,
          status: 'pending',
          processed: 0,
          failed: 0,
          total: detail.images.length,
        }))

        setGroups(editableGroups)
        setTagVocab(parseTagVocabulary(categories))
        setAuthorSuggestions(authors)
        setActiveTab(editableGroups.length > 1 ? ALL_TAB : 0)
      })
      .catch((err: unknown) => {
        setLoadError(getApiErrorMessage(err, 'Failed to load imported groups'))
      })
      .finally(() => {
        setLoading(false)
      })
  }, [
    open,
    groupIds,
    isImportReview,
    resetLoad,
    setGroups,
    setTagVocab,
    setAuthorSuggestions,
    setActiveTab,
  ])

  return {
    loading,
    loadError,
    isMassEdit,
    isImportReview,
    ungroupedCount,
    resetLoad,
  }
}
