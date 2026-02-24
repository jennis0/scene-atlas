import { useState, useEffect, useCallback, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Check,
  Loader2,
  X,
  Trash2,
  Search,
  Pencil,
  Merge,
  MoreHorizontal,
  EyeOff,
} from 'lucide-react'
import { groupApi, tagApi, imageApi, getThumbnailUrlById, getImageUrlById } from '@/lib/api'
import { getApiErrorMessage, isNotFoundError } from '@/lib/getErrorMessage'
import { SAVED_INDICATOR_DURATION_MS } from '@/lib/constants'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import type {
  EditableFileState,
  EditableGroupState,
  Image,
  GroupEditRequest,
  GroupSearchItem,
} from '@/types'
import { MergeGroupPicker } from './MergeGroupPicker'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { FileCard } from './import/FileCard'
import { FileToolbar } from './import/FileToolbar'
import { MetadataForm } from './import/MetadataForm'
import { SubgroupHeading } from './SubgroupHeading'
import { parseTagVocabulary } from './import/types'
import { EMPTY_FILTER, applyFileFilter } from './import/fileFilter'
import { useFileEditing, ALL_TAB } from '@/hooks/useFileEditing'

interface EditGroupDialogProps {
  // Single-group mode: pass groupId
  groupId?: number | null
  // Mass-edit mode: pass seedImages (the search result images to edit)
  seedImages?: Image[]
  // Import-review mode: pass groupIds to load multiple groups by ID, all images in scope
  groupIds?: number[]
  open: boolean
  onClose: () => void
  onSave: () => void
}

function imageToEditable(img: Image, outOfScope = false): EditableFileState {
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

function buildPayload(group: EditableGroupState): GroupEditRequest {
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

export function EditGroupDialog({
  groupId,
  seedImages,
  groupIds,
  open,
  onClose,
  onSave,
}: EditGroupDialogProps) {
  const isMassEdit = !!seedImages && seedImages.length > 0
  const isImportReview = !!groupIds && groupIds.length > 0
  const queryClient = useQueryClient()

  const invalidateGallery = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['search'] })
    queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
  }, [queryClient])

  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  // `saving` = a structural operation (delete/merge/split) is in progress — disables UI
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [showMergePicker, setShowMergePicker] = useState(false)
  const [merging, setMerging] = useState(false)
  // Per-group auto-save tracking
  const [groupSaving, setGroupSaving] = useState<Set<string>>(new Set())
  const [groupSaved, setGroupSaved] = useState<Set<string>>(new Set())
  // Per-group nav actions (mass-edit mode)
  const [mergeSourceGroupId, setMergeSourceGroupId] = useState<string | null>(null)
  const [deleteConfirmGroupId, setDeleteConfirmGroupId] = useState<string | null>(null)
  const [ungroupedCount, setUngroupedCount] = useState(0)

  // ── Auto-save ────────────────────────────────────────────────────────

  const autoSaveGroup = useCallback(async (group: EditableGroupState) => {
    const gId = Number(group.id)
    if (isNaN(gId)) return // Skip locally-created groups (UUID keys — not in DB yet)

    setGroupSaving((prev) => {
      const s = new Set(prev)
      s.add(group.id)
      return s
    })
    setSaveError(null)
    try {
      await groupApi.edit(gId, buildPayload(group))
      invalidateGallery()
      setGroupSaved((prev) => {
        const s = new Set(prev)
        s.add(group.id)
        return s
      })
      setTimeout(() => {
        setGroupSaved((prev) => {
          const s = new Set(prev)
          s.delete(group.id)
          return s
        })
      }, SAVED_INDICATOR_DURATION_MS)
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Auto-save failed'))
    } finally {
      setGroupSaving((prev) => {
        const s = new Set(prev)
        s.delete(group.id)
        return s
      })
    }
    // All deps (state setters, invalidateGallery, groupApi) are stable refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Shared file editing state and mutations ───────────────────────

  const {
    groups,
    setGroups,
    activeTab,
    setActiveTab,
    selections,
    fileFilter,
    setFileFilter,
    editingSvHeading,
    setEditingSvHeading,
    tagVocab,
    setTagVocab,
    authorSuggestions,
    setAuthorSuggestions,
    updateGroup,
    updateFile,
    updateFileAnyGroup,
    toggleFileSelection,
    selectAllVisible,
    deselectAll,
    bulkAddTag,
    bulkSetGrid,
    bulkSetImageType,
    bulkSetSubgroup,
    bulkExclude,
    clearSubgroupLabel,
    renameSubgroup,
    isAllTab,
    activeGroup,
    activeGroupId,
    allSameAuthor,
  } = useFileEditing({ onGroupChange: (affected) => affected.forEach(autoSaveGroup) })

  const reset = useCallback(() => {
    setLoading(false)
    setLoadError(null)
    setSaving(false)
    setSaveError(null)
    setConfirmingDelete(false)
    setShowMergePicker(false)
    setMerging(false)
    setGroupSaving(new Set())
    setGroupSaved(new Set())
    setMergeSourceGroupId(null)
    setDeleteConfirmGroupId(null)
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
      reset()
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
    reset,
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

    const groupIds = [...byGroup.keys()]
    if (groupIds.length === 0) {
      setLoadError('None of the search results belong to a variant group.')
      setLoading(false)
      return
    }

    setUngroupedCount(ungrouped)

    Promise.all([
      ...groupIds.map((id) => groupApi.get(id)),
      tagApi.getCategories(),
      imageApi.getAuthors(),
    ])
      .then((results) => {
        const groupDetails = results.slice(0, groupIds.length) as Awaited<
          ReturnType<typeof groupApi.get>
        >[]
        const categories = results[groupIds.length] as Awaited<
          ReturnType<typeof tagApi.getCategories>
        >
        const authors = results[groupIds.length + 1] as string[]

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
    reset,
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
    reset,
    setGroups,
    setTagVocab,
    setAuthorSuggestions,
    setActiveTab,
  ])

  // ── Close / Done ────────────────────────────────────────────────

  // Called on any close action — changes have already been auto-saved
  const handleDone = useCallback(() => {
    onSave()
    onClose()
  }, [onSave, onClose])

  // ── moveToNewGroup (API-backed split) ──────────────────────────

  // Only available in single-group mode — triggers an immediate API call
  const moveToNewGroup = async (sourceGroupId: string) => {
    const sourceIndex = groups.findIndex((g) => g.id === sourceGroupId)
    if (sourceIndex === -1) return
    const source = groups[sourceIndex]
    const sel = selections[sourceGroupId] ?? new Set<string>()
    if (sel.size === 0) return
    const sourceGId = Number(sourceGroupId)
    if (isNaN(sourceGId)) return

    const movedFiles = source.files.filter((f) => sel.has(f.relative_path))
    const remainingFiles = source.files.filter((f) => !sel.has(f.relative_path))

    setSaving(true)
    setSaveError(null)
    try {
      const response = await groupApi.edit(sourceGId, {
        base_name: source.group_name,
        author: source.author || undefined,
        images: remainingFiles
          .filter((f) => !f.excluded)
          .map((f) => ({
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
        new_groups: [
          {
            base_name: `${source.group_name} (split)`,
            author: source.author || undefined,
            image_ids: movedFiles.filter((f) => !f.excluded).map((f) => Number(f.relative_path)),
          },
        ],
      })

      // Reload both groups from API so we have real IDs
      const newGroupId = response.new_group_ids[0]
      const fetches: Promise<Awaited<ReturnType<typeof groupApi.get>>>[] = [groupApi.get(sourceGId)]
      if (newGroupId) fetches.push(groupApi.get(newGroupId))
      const [updatedSource, newGroup] = await Promise.all(fetches)

      const toEditable = (g: typeof updatedSource): EditableGroupState => ({
        id: String(g.id),
        author: g.author ?? '',
        group_name: g.base_name,
        files: g.images.map((img) => imageToEditable(img)),
        skip: false,
        status: 'pending',
        processed: 0,
        failed: 0,
        total: g.images.length,
      })

      const newGroups = [
        ...groups.map((g, i) => (i === sourceIndex ? toEditable(updatedSource) : g)),
        ...(newGroup ? [toEditable(newGroup)] : []),
      ]
      setGroups(newGroups)
      setActiveTab(newGroups.length - 1)
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Split failed'))
    } finally {
      setSaving(false)
    }
  }

  // ── Delete group (single-group mode only) ──────────────────────

  const handleDelete = async () => {
    const gId = groupId ?? null
    if (gId === null) return
    setSaving(true)
    try {
      await groupApi.delete(gId)
      onSave()
      onClose()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Delete failed'))
      setSaving(false)
      setConfirmingDelete(false)
    }
  }

  // ── Merge into another group (single-group mode only) ──────────

  const handleMerge = async (targetGroup: { id: number }) => {
    const gId = groupId ?? null
    if (gId === null) return
    setMerging(true)
    try {
      await groupApi.merge(gId, targetGroup.id)
      setShowMergePicker(false)
      onSave()
      onClose()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge failed'))
      setMerging(false)
    }
  }

  // ── Per-group nav actions (mass-edit mode) ─────────────────────

  const handleDeleteGroup = async (gId: string) => {
    const idx = groups.findIndex((g) => g.id === gId)
    setSaving(true)
    setSaveError(null)
    try {
      await groupApi.delete(Number(gId))
      setGroups((prev) => prev.filter((g) => g.id !== gId))
      setDeleteConfirmGroupId(null)
      if (activeTab !== ALL_TAB) {
        if (idx < activeTab) setActiveTab(activeTab - 1)
        else if (idx === activeTab) setActiveTab(Math.max(0, activeTab - 1))
      }
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Delete failed'))
    } finally {
      setSaving(false)
    }
  }

  const handleMergeGroup = async (sourceId: string, targetGroup: GroupSearchItem) => {
    const idx = groups.findIndex((g) => g.id === sourceId)
    setMerging(true)
    setSaveError(null)
    try {
      await groupApi.merge(Number(sourceId), targetGroup.id)

      // If target group is also open in this dialog, reload it from the API
      const targetInGroups = groups.some((g) => g.id === String(targetGroup.id))
      let updatedGroups = groups.filter((g) => g.id !== sourceId)

      if (targetInGroups) {
        const reloaded = await groupApi.get(targetGroup.id)
        // Preserve outOfScope flags for the target group's existing images
        const originalTarget = groups.find((g) => g.id === String(targetGroup.id))
        const originalSeedIds = new Set(
          originalTarget?.files.filter((f) => !f.outOfScope).map((f) => Number(f.relative_path)) ??
            [],
        )
        updatedGroups = updatedGroups.map((g) => {
          if (g.id !== String(targetGroup.id)) return g
          return {
            ...g,
            files: reloaded.images.map((img) => imageToEditable(img, !originalSeedIds.has(img.id))),
            total: reloaded.images.length,
          }
        })
      }

      setGroups(updatedGroups)
      setMergeSourceGroupId(null)
      if (activeTab !== ALL_TAB) {
        if (idx < activeTab) setActiveTab(activeTab - 1)
        else if (idx === activeTab) setActiveTab(Math.max(0, activeTab - 1))
      }
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge failed'))
    } finally {
      setMerging(false)
    }
  }

  // ── Remove group from view (mass-edit only, no delete) ────────

  const removeGroupFromView = (gId: string) => {
    const idx = groups.findIndex((g) => g.id === gId)
    setGroups((prev) => prev.filter((g) => g.id !== gId))
    if (activeTab !== ALL_TAB) {
      if (idx < activeTab) setActiveTab(activeTab - 1)
      else if (idx === activeTab) setActiveTab(ALL_TAB)
    }
  }

  // ── Merge all groups (mass-edit only) ────────────────────────

  const [confirmingMergeAll, setConfirmingMergeAll] = useState(false)

  const handleMergeAll = async () => {
    if (groups.length < 2) return
    const target = groups[0]
    const sources = groups.slice(1)
    setMerging(true)
    setSaveError(null)
    setConfirmingMergeAll(false)
    try {
      for (const source of sources) {
        await groupApi.merge(Number(source.id), Number(target.id))
      }
      // Reload the merged target from API
      const reloaded = await groupApi.get(Number(target.id))
      const seedIds = new Set(
        groups.flatMap((g) =>
          g.files.filter((f) => !f.outOfScope).map((f) => Number(f.relative_path)),
        ),
      )
      setGroups([
        {
          id: String(reloaded.id),
          author: reloaded.author ?? '',
          group_name: reloaded.base_name,
          files: reloaded.images.map((img) => imageToEditable(img, !seedIds.has(img.id))),
          skip: false,
          status: 'pending',
          processed: 0,
          failed: 0,
          total: reloaded.images.length,
        },
      ])
      setActiveTab(0)
      invalidateGallery()
    } catch (err) {
      setSaveError(getApiErrorMessage(err, 'Merge all failed'))
    } finally {
      setMerging(false)
    }
  }

  // ── Derived values ─────────────────────────────────────────────

  // All tab shows only in-scope files; per-group tab shows all (incl. out-of-scope for context)
  const allInScopeFiles = useMemo(
    () => groups.flatMap((g) => g.files.filter((f) => !f.outOfScope)),
    [groups],
  )
  const perGroupFiles = activeGroup?.files ?? []
  const sourceFiles = isAllTab ? allInScopeFiles : perGroupFiles

  // Filtered files: for the in-scope section, filter normally; out-of-scope shown separately
  const inScopeSource = useMemo(() => sourceFiles.filter((f) => !f.outOfScope), [sourceFiles])
  const filteredInScope = useMemo(
    () => applyFileFilter(inScopeSource, fileFilter),
    [inScopeSource, fileFilter],
  )
  const outOfScopeFiles = useMemo(
    () => (!isAllTab ? (activeGroup?.files ?? []).filter((f) => f.outOfScope) : []),
    [isAllTab, activeGroup],
  )

  const activeSelection = selections[activeGroupId] ?? new Set<string>()

  const groupSubVariants = useMemo(
    () =>
      [
        ...new Set(
          inScopeSource.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string),
        ),
      ].sort(),
    [inScopeSource],
  )

  const distinctSubVariants = useMemo(
    () =>
      [...new Set(filteredInScope.map((f) => f.subgroup))].sort((a, b) => {
        if (a === null) return -1
        if (b === null) return 1
        return (a ?? '').localeCompare(b ?? '')
      }),
    [filteredInScope],
  )

  const showSubVariantHeadings = distinctSubVariants.length > 1
  const subVariantGroups = distinctSubVariants.map((sv) => ({
    subVariant: sv,
    files: filteredInScope.filter((f) => f.subgroup === sv),
  }))

  const hasActiveFilter = fileFilter.text || fileFilter.active.length > 0
  const isOriginalGroup = !isAllTab && !isMassEdit && activeGroup?.id === String(groupId)

  const totalInScope = groups.reduce(
    (s, g) => s + g.files.filter((f) => !f.outOfScope && !f.excluded).length,
    0,
  )

  const isBusy = saving || groupSaving.size > 0

  // ── Render ─────────────────────────────────────────────────────

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !saving) handleDone()
      }}
    >
      <DialogContent className="max-w-5xl h-[85vh] overflow-hidden flex flex-col p-0 gap-0">
        {/* Amber stripe */}
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-xl" />

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 pt-6 pb-3 shrink-0">
          <div>
            <h2 className="font-display text-lg font-semibold flex items-center gap-2 text-foreground">
              <Pencil className="h-5 w-5 text-primary shrink-0" />
              {isMassEdit ? 'Edit Search Results' : 'Edit Group'}
            </h2>
            {isMassEdit && !loading && !loadError && groups.length > 0 && (
              <p className="text-[11px] text-muted-foreground/60 mt-0.5 ml-7">
                {totalInScope} image{totalInScope !== 1 ? 's' : ''} across {groups.length} group
                {groups.length !== 1 ? 's' : ''}
                {ungroupedCount > 0 && ` · ${ungroupedCount} ungrouped skipped`}
              </p>
            )}
          </div>
          <button
            onClick={handleDone}
            disabled={saving}
            className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {/* Amber rule */}
        <div className="h-px bg-gradient-to-r from-primary/60 via-primary/20 to-transparent mx-6 shrink-0" />

        {/* ── Loading ── */}
        {loading && (
          <div className="flex items-center justify-center flex-1">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {/* ── Load error ── */}
        {!loading && loadError && (
          <div className="mx-6 mt-4 flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {loadError}
          </div>
        )}

        {/* ── Main content ── */}
        {!loading && !loadError && groups.length > 0 && (
          <div className="flex min-h-0 flex-1 overflow-hidden">
            {/* ── Left: groups nav (only when >1 group) ── */}
            {groups.length > 1 && (
              <div className="w-[190px] shrink-0 border-r border-border/30 flex flex-col overflow-hidden bg-muted/20">
                <div className="px-3 py-2.5 border-b border-border/30 shrink-0">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold">
                    {groups.length} groups
                  </span>
                </div>

                <div className="flex-1 overflow-y-auto py-1">
                  {/* "All" entry */}
                  <button
                    onClick={() => setActiveTab(ALL_TAB)}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 ${
                      isAllTab
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                    }`}
                  >
                    <span className="font-display text-[13px] font-semibold flex-1">All</span>
                    <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
                      {groups.reduce(
                        (s, g) => s + g.files.filter((f) => !f.excluded && !f.outOfScope).length,
                        0,
                      )}
                    </span>
                  </button>
                  <div className="h-px bg-border/30 mx-3 my-0.5" />

                  {groups.map((g, i) => (
                    <div key={g.id} className="group/navrow">
                      {deleteConfirmGroupId === g.id ? (
                        <div className="px-3 py-2 border-l-2 border-destructive/50 bg-destructive/5">
                          <p className="text-[11px] text-destructive/80 mb-1.5">
                            Delete this group?
                          </p>
                          <div className="flex gap-1">
                            <button
                              onClick={() => handleDeleteGroup(g.id)}
                              disabled={saving}
                              className="px-2 py-0.5 rounded border border-destructive/50 bg-destructive/10 text-destructive text-[10px] hover:bg-destructive/20 transition-colors disabled:opacity-50"
                            >
                              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Delete'}
                            </button>
                            <button
                              onClick={() => setDeleteConfirmGroupId(null)}
                              disabled={saving}
                              className="px-2 py-0.5 rounded border border-border bg-secondary text-muted-foreground text-[10px] hover:text-foreground transition-colors disabled:opacity-50"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-center">
                          <button
                            onClick={() => setActiveTab(i)}
                            className={`flex-1 flex items-center gap-2 pl-3 pr-1 py-2 text-left transition-colors border-l-2 min-w-0 ${
                              activeTab === i
                                ? 'border-primary bg-primary/10 text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                            }`}
                          >
                            <span className="flex-1 text-[12px] truncate">{g.group_name}</span>
                            <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0 flex items-center gap-1">
                              {g.files.filter((f) => !f.excluded && !f.outOfScope).length}
                              {g.files.some((f) => f.outOfScope) && (
                                <span className="ml-0.5 opacity-50">
                                  +{g.files.filter((f) => f.outOfScope).length}
                                </span>
                              )}
                              {groupSaving.has(g.id) ? (
                                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/40 ml-1" />
                              ) : groupSaved.has(g.id) ? (
                                <Check className="h-3 w-3 text-green-500/70 ml-1" />
                              ) : null}
                            </span>
                          </button>
                          {isMassEdit && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <button
                                  className="opacity-0 group-hover/navrow:opacity-100 focus:opacity-100 h-7 w-6 mr-1 flex items-center justify-center rounded text-muted-foreground/50 hover:text-foreground hover:bg-secondary transition-all shrink-0"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <MoreHorizontal className="h-3.5 w-3.5" />
                                </button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => setMergeSourceGroupId(g.id)}>
                                  <Merge className="h-4 w-4 mr-2" />
                                  Merge into…
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => removeGroupFromView(g.id)}>
                                  <EyeOff className="h-4 w-4 mr-2" />
                                  Remove from view
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  onClick={() => setDeleteConfirmGroupId(g.id)}
                                  className="text-destructive focus:text-destructive"
                                >
                                  <Trash2 className="h-4 w-4 mr-2" />
                                  Delete group
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {/* Merge All button */}
                {isMassEdit && groups.length >= 2 && (
                  <div className="p-2.5 border-t border-border/30 shrink-0">
                    <button
                      onClick={() => setConfirmingMergeAll(true)}
                      disabled={merging || saving}
                      className="w-full text-[12px] py-1.5 rounded border border-border/40 bg-secondary/30 text-muted-foreground hover:bg-secondary/60 hover:text-foreground transition-colors flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Merge className="h-3.5 w-3.5" />
                      {merging ? 'Merging…' : 'Merge All'}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* ── Right: active group content ── */}
            <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
              {/* Group metadata */}
              <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0">
                <MetadataForm
                  author={isAllTab ? allSameAuthor : (activeGroup?.author ?? '')}
                  groupName={isAllTab ? '' : (activeGroup?.group_name ?? '')}
                  authorPlaceholder={
                    isAllTab && !allSameAuthor
                      ? 'Multiple — type to set for all groups'
                      : 'Author name'
                  }
                  groupNamePlaceholder={isAllTab ? '— (select a group to rename)' : 'Group name'}
                  groupNameDisabled={isAllTab}
                  isMassEdit={isMassEdit}
                  isAllTab={isAllTab}
                  authorSuggestions={authorSuggestions}
                  suggestionsListId="author-suggestions-edit"
                  onAuthorChange={(val) => {
                    if (isAllTab) {
                      setGroups((prev) => prev.map((g) => ({ ...g, author: val })))
                    } else {
                      updateGroup(activeTab, { author: val })
                    }
                  }}
                  onGroupNameChange={(val) =>
                    !isAllTab && updateGroup(activeTab, { group_name: val })
                  }
                  onBlur={() => {
                    if (isAllTab) {
                      groups.forEach(autoSaveGroup)
                    } else if (activeGroup) {
                      autoSaveGroup(activeGroup)
                    }
                  }}
                />
              </div>

              {/* File toolbar */}
              <div className="px-5 shrink-0">
                <FileToolbar
                  files={inScopeSource}
                  filteredFiles={filteredInScope}
                  selection={activeSelection}
                  filter={fileFilter}
                  vocab={tagVocab}
                  onFilterChange={setFileFilter}
                  onSelectAll={() => selectAllVisible(activeGroupId, filteredInScope)}
                  onDeselectAll={() => deselectAll(activeGroupId)}
                  onBulkAddTag={(tag) => bulkAddTag(isAllTab ? null : activeGroupId, tag)}
                  onBulkSetGrid={(gridded, gridType) =>
                    bulkSetGrid(isAllTab ? null : activeGroupId, gridded, gridType)
                  }
                  onBulkSetImageType={(v) => bulkSetImageType(isAllTab ? null : activeGroupId, v)}
                  onBulkSetSubgroup={(v) => bulkSetSubgroup(isAllTab ? null : activeGroupId, v)}
                  onBulkExclude={() => bulkExclude(isAllTab ? null : activeGroupId)}
                  onMoveToNewGroup={
                    !isAllTab && !isMassEdit && activeGroup?.id
                      ? () => moveToNewGroup(activeGroup.id)
                      : undefined
                  }
                  excludeLabel={isMassEdit ? 'Remove' : 'Delete'}
                  alwaysShowTypeToggle
                />
              </div>

              {/* File gallery */}
              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
                {showSubVariantHeadings ? (
                  subVariantGroups.map((svGroup) => {
                    const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
                    const isEditing =
                      !isAllTab &&
                      editingSvHeading === svGroup.subVariant &&
                      svGroup.subVariant !== null
                    return (
                      <div key={svGroup.subVariant ?? '__main__'} className="mb-2">
                        <SubgroupHeading
                          subgroup={svGroup.subVariant}
                          count={nonExcluded}
                          isEditing={isEditing}
                          existingSubgroups={groupSubVariants}
                          onStartEdit={() => setEditingSvHeading(svGroup.subVariant!)}
                          onCommit={(val) => {
                            renameSubgroup(activeGroup!.id, svGroup.subVariant!, val)
                            setEditingSvHeading(null)
                          }}
                          onCancel={() => setEditingSvHeading(null)}
                          onClear={() => clearSubgroupLabel(activeGroup!.id, svGroup.subVariant!)}
                          canEdit={!isAllTab}
                        />
                        <div className="space-y-1.5 pb-2">
                          {svGroup.files.map((file) => (
                            <FileCard
                              key={file.relative_path}
                              file={file}
                              jobId=""
                              vocab={tagVocab}
                              existingSubgroups={groupSubVariants}
                              selected={activeSelection.has(file.relative_path)}
                              onToggleSelect={() =>
                                toggleFileSelection(activeGroupId, file.relative_path)
                              }
                              onUpdate={(updates) =>
                                isAllTab
                                  ? updateFileAnyGroup(file.relative_path, updates)
                                  : updateFile(activeTab, file.relative_path, updates)
                              }
                              excludeTooltip={
                                isMassEdit ? 'Remove from group' : 'Mark for deletion'
                              }
                            />
                          ))}
                        </div>
                      </div>
                    )
                  })
                ) : (
                  <div className="space-y-1.5">
                    {filteredInScope.map((file) => (
                      <FileCard
                        key={file.relative_path}
                        file={file}
                        jobId=""
                        vocab={tagVocab}
                        existingSubgroups={groupSubVariants}
                        selected={activeSelection.has(file.relative_path)}
                        onToggleSelect={() =>
                          toggleFileSelection(activeGroupId, file.relative_path)
                        }
                        onUpdate={(updates) =>
                          isAllTab
                            ? updateFileAnyGroup(file.relative_path, updates)
                            : updateFile(activeTab, file.relative_path, updates)
                        }
                        excludeTooltip={isMassEdit ? 'Remove from group' : 'Mark for deletion'}
                      />
                    ))}
                  </div>
                )}

                {filteredInScope.length === 0 && hasActiveFilter && (
                  <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
                    <Search className="h-8 w-8 text-muted-foreground/30" />
                    <p className="text-sm">No files match the current filter</p>
                  </div>
                )}

                {/* Out-of-scope files — shown in per-group tab only, as context */}
                {outOfScopeFiles.length > 0 && (
                  <div className="mt-4">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="flex-1 h-px bg-border/20" />
                      <span className="text-[10px] font-semibold text-muted-foreground/40 uppercase tracking-wider whitespace-nowrap">
                        Other images in this group
                      </span>
                      <div className="flex-1 h-px bg-border/20" />
                    </div>
                    <div className="space-y-1.5">
                      {outOfScopeFiles.map((file) => (
                        <FileCard
                          key={file.relative_path}
                          file={file}
                          jobId=""
                          vocab={tagVocab}
                          existingSubgroups={groupSubVariants}
                          selected={false}
                          onToggleSelect={() => {}}
                          onUpdate={(updates) => updateFile(activeTab, file.relative_path, updates)}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* ── Footer ── */}
              <div className="px-5 py-3 border-t border-border/30 shrink-0 flex items-center justify-between gap-3">
                {/* Delete group (single-group mode only, for the original persisted group) */}
                {isOriginalGroup ? (
                  confirmingDelete ? (
                    <div className="flex items-center gap-2 text-sm text-destructive">
                      <span>Delete this group and all its images?</span>
                      <button
                        onClick={handleDelete}
                        disabled={saving}
                        className="px-2.5 py-1 text-xs rounded border border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors disabled:opacity-50"
                      >
                        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Confirm'}
                      </button>
                      <button
                        onClick={() => setConfirmingDelete(false)}
                        disabled={saving}
                        className="px-2.5 py-1 text-xs rounded border border-border bg-secondary text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setConfirmingDelete(true)}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded text-destructive/70 hover:text-destructive hover:bg-destructive/10 transition-colors"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete Group
                      </button>
                      <button
                        onClick={() => setShowMergePicker(true)}
                        disabled={saving || merging}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50"
                      >
                        <Merge className="h-3.5 w-3.5" />
                        Merge into…
                      </button>
                    </div>
                  )
                ) : (
                  <div />
                )}

                {/* Save status + Done */}
                <div className="flex items-center gap-2">
                  {saveError && (
                    <span className="text-xs text-destructive flex items-center gap-1 max-w-xs truncate">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                      {saveError}
                    </span>
                  )}
                  {!saveError && groupSaving.size > 0 && (
                    <span className="text-xs text-muted-foreground/60 flex items-center gap-1">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Saving…
                    </span>
                  )}
                  {!saveError && groupSaving.size === 0 && groupSaved.size > 0 && (
                    <span className="text-xs text-green-500/70 flex items-center gap-1">
                      <Check className="h-3 w-3" />
                      Saved
                    </span>
                  )}
                  <button
                    onClick={handleDone}
                    disabled={isBusy}
                    className="px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40"
                  >
                    {saving ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
                        Working…
                      </>
                    ) : groupSaving.size > 0 ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
                        Saving…
                      </>
                    ) : (
                      'Done'
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </DialogContent>

      {/* Merge picker — shared for footer (single-group) and nav (mass-edit) actions */}
      <MergeGroupPicker
        open={showMergePicker || mergeSourceGroupId !== null}
        onClose={() => {
          setShowMergePicker(false)
          setMergeSourceGroupId(null)
        }}
        excludeGroupId={mergeSourceGroupId !== null ? Number(mergeSourceGroupId) : groupId}
        onSelect={(target) =>
          mergeSourceGroupId ? handleMergeGroup(mergeSourceGroupId, target) : handleMerge(target)
        }
        currentGroupName={
          mergeSourceGroupId !== null
            ? groups.find((g) => g.id === mergeSourceGroupId)?.group_name
            : activeGroup?.group_name
        }
      />

      {/* Merge all confirmation (mass-edit mode) */}
      <ConfirmDialog
        open={confirmingMergeAll}
        onOpenChange={setConfirmingMergeAll}
        title="Merge All Groups"
        description={`This will merge all ${groups.length} groups into "${groups[0]?.group_name ?? ''}". This cannot be undone.`}
        confirmLabel="Merge All"
        confirmVariant="default"
        loadingLabel="Merging…"
        onConfirm={handleMergeAll}
        isLoading={merging}
      />
    </Dialog>
  )
}
