import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  AlertCircle,
  Loader2,
  X,
  Trash2,
  Search,
  Pencil,
  Merge,
} from 'lucide-react'
import { variantGroupApi, tagApi, imageApi, getThumbnailUrlById, getImageUrlById } from '@/lib/api'
import {
  Dialog,
  DialogContent,
} from '@/components/ui/dialog'
import type {
  EditableFileState,
  EditableGroupState,
  TagData,
  Image,
  VariantGroupEditRequest,
} from '@/types'
import { MergeGroupPicker } from './MergeGroupPicker'
import { FileCard } from './import/FileCard'
import { FileToolbar } from './import/FileToolbar'
import { parseTagVocabulary } from './import/types'
import type { ParsedTagVocab } from './import/types'
import { EMPTY_FILTER, applyFileFilter } from './import/fileFilter'
import type { FileFilter } from './import/fileFilter'

const ALL_TAB = -1
const ALL_GROUP_ID = '__all__'

interface EditGroupDialogProps {
  // Single-group mode: pass groupId
  groupId?: number | null
  // Mass-edit mode: pass seedImages (the search result images to edit)
  seedImages?: Image[]
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
    sub_variant: img.sub_variant ?? null,
    excluded: false,
    outOfScope,
    previewUrl: getThumbnailUrlById(img.id),
    fullImageUrl: getImageUrlById(img.id),
  }
}

export function EditGroupDialog({ groupId, seedImages, open, onClose, onSave }: EditGroupDialogProps) {
  const isMassEdit = !!seedImages && seedImages.length > 0

  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [showMergePicker, setShowMergePicker] = useState(false)
  const [merging, setMerging] = useState(false)
  const [ungroupedCount, setUngroupedCount] = useState(0)

  const [groups, setGroups] = useState<EditableGroupState[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [tagVocab, setTagVocab] = useState<ParsedTagVocab[]>([])
  const [selections, setSelections] = useState<Record<string, Set<string>>>({})
  const [fileFilter, setFileFilter] = useState<FileFilter>(EMPTY_FILTER)
  const [authorSuggestions, setAuthorSuggestions] = useState<string[]>([])

  // Sub-variant heading inline rename state
  const [editingSvHeading, setEditingSvHeading] = useState<string | null>(null)
  const [svHeadingDraft, setSvHeadingDraft] = useState('')

  const reset = useCallback(() => {
    setLoading(false)
    setLoadError(null)
    setSaving(false)
    setSaveError(null)
    setConfirmingDelete(false)
    setShowMergePicker(false)
    setMerging(false)
    setUngroupedCount(0)
    setGroups([])
    setActiveTab(0)
    setSelections({})
    setFileFilter(EMPTY_FILTER)
    setEditingSvHeading(null)
  }, [])

  useEffect(() => { setFileFilter(EMPTY_FILTER); setEditingSvHeading(null) }, [activeTab])

  // ── Load: single-group mode ──────────────────────────────────────────

  useEffect(() => {
    if (!open || isMassEdit) return
    const gId = groupId ?? null
    if (gId === null) { reset(); return }

    setLoading(true)
    setLoadError(null)

    Promise.all([
      variantGroupApi.get(gId),
      tagApi.getCategories(),
      imageApi.getAuthors(),
    ]).then(([group, categories, authors]) => {
      setGroups([{
        id: String(group.id),
        author: group.author ?? '',
        variant_group_name: group.base_name,
        files: group.images.map((img) => imageToEditable(img)),
        skip: false,
        status: 'pending',
        processed: 0,
        failed: 0,
        total: group.images.length,
      }])
      setTagVocab(parseTagVocabulary(categories))
      setAuthorSuggestions(authors)
      setActiveTab(0)
      setSelections({})
    }).catch((err) => {
      setLoadError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load group')
    }).finally(() => {
      setLoading(false)
    })
  }, [open, groupId, isMassEdit, reset])

  // ── Load: mass-edit mode ─────────────────────────────────────────────

  useEffect(() => {
    if (!open || !isMassEdit) return

    setLoading(true)
    setLoadError(null)

    // Group seed images by variant_group_id
    const byGroup = new Map<number, Image[]>()
    let ungrouped = 0
    for (const img of seedImages!) {
      if (img.variant_group_id === null) {
        ungrouped++
      } else {
        const list = byGroup.get(img.variant_group_id) ?? []
        list.push(img)
        byGroup.set(img.variant_group_id, list)
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
      ...groupIds.map((id) => variantGroupApi.get(id)),
      tagApi.getCategories(),
      imageApi.getAuthors(),
    ]).then((results) => {
      const groupDetails = results.slice(0, groupIds.length) as Awaited<ReturnType<typeof variantGroupApi.get>>[]
      const categories = results[groupIds.length] as Awaited<ReturnType<typeof tagApi.getCategories>>
      const authors = results[groupIds.length + 1] as string[]

      const editableGroups: EditableGroupState[] = groupDetails.map((detail) => {
        const seedIds = new Set((byGroup.get(detail.id) ?? []).map((img) => img.id))
        return {
          id: String(detail.id),
          author: detail.author ?? '',
          variant_group_name: detail.base_name,
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
      setSelections({})
    }).catch((err) => {
      setLoadError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load groups')
    }).finally(() => {
      setLoading(false)
    })
  }, [open, seedImages, isMassEdit, reset])  // eslint-disable-line react-hooks/exhaustive-deps

  // ── State helpers ──────────────────────────────────────────────────

  const updateGroup = (index: number, updates: Partial<EditableGroupState>) => {
    setGroups((prev) => prev.map((g, i) => (i === index ? { ...g, ...updates } : g)))
  }

  const updateFile = (groupIndex: number, relativePath: string, updates: Partial<EditableFileState>) => {
    setGroups((prev) =>
      prev.map((g, i) =>
        i === groupIndex
          ? { ...g, files: g.files.map((f) => (f.relative_path === relativePath ? { ...f, ...updates } : f)) }
          : g
      )
    )
  }

  const updateFileAnyGroup = (relativePath: string, updates: Partial<EditableFileState>) => {
    setGroups((prev) =>
      prev.map((g) => ({ ...g, files: g.files.map((f) => (f.relative_path === relativePath ? { ...f, ...updates } : f)) }))
    )
  }

  // ── Selection helpers ──────────────────────────────────────────────

  const toggleFileSelection = (gId: string, relativePath: string) => {
    setSelections((prev) => {
      const set = new Set(prev[gId] ?? [])
      if (set.has(relativePath)) set.delete(relativePath)
      else set.add(relativePath)
      return { ...prev, [gId]: set }
    })
  }

  const selectAllVisible = (gId: string, visibleFiles: EditableFileState[]) => {
    setSelections((prev) => {
      const set = new Set<string>(prev[gId] ?? [])
      visibleFiles.filter((f) => !f.excluded && !f.outOfScope).forEach((f) => set.add(f.relative_path))
      return { ...prev, [gId]: set }
    })
  }

  const deselectAll = (gId: string) => {
    setSelections((prev) => ({ ...prev, [gId]: new Set<string>() }))
  }

  // ── Bulk actions (gId: null = All mode) ───────────────────────────

  const bulkAddTag = (gId: string | null, tag: TagData) => {
    const selId = gId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (gId !== null && g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) => {
            if (!sel.has(f.relative_path) || f.excluded || f.outOfScope) return f
            if (f.tags.some((t) => t.category === tag.category && t.value === tag.value)) return f
            return { ...f, tags: [...f.tags, tag] }
          }),
        }
      })
    )
  }

  const bulkSetGrid = (gId: string | null, value: boolean | null) => {
    const selId = gId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (gId !== null && g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            !sel.has(f.relative_path) || f.excluded || f.outOfScope ? f : { ...f, gridded: value }
          ),
        }
      })
    )
  }

  const bulkSetSubVariant = (gId: string | null, value: string) => {
    const selId = gId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    const normalized = value.trim() || null
    setGroups((prev) =>
      prev.map((g) => {
        if (gId !== null && g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            !sel.has(f.relative_path) || f.excluded || f.outOfScope ? f : { ...f, sub_variant: normalized }
          ),
        }
      })
    )
  }

  const bulkExclude = (gId: string | null) => {
    const selId = gId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (gId !== null && g.id !== gId) return g
        return { ...g, files: g.files.map((f) => (!sel.has(f.relative_path) || f.outOfScope ? f : { ...f, excluded: true })) }
      })
    )
    deselectAll(selId)
  }

  const clearSubVariantLabel = (gId: string, subVariant: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            f.sub_variant === subVariant && !f.excluded && !f.outOfScope ? { ...f, sub_variant: null } : f
          ),
        }
      })
    )
  }

  const renameSubVariant = (gId: string, oldVal: string, newVal: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            f.sub_variant === oldVal && !f.excluded && !f.outOfScope ? { ...f, sub_variant: newVal.trim() || null } : f
          ),
        }
      })
    )
  }

  // Only available in single-group mode
  const moveToNewGroup = (sourceGroupId: string) => {
    const sourceIndex = groups.findIndex((g) => g.id === sourceGroupId)
    if (sourceIndex === -1) return
    const source = groups[sourceIndex]
    const sel = selections[sourceGroupId] ?? new Set<string>()
    if (sel.size === 0) return

    const movedFiles = source.files.filter((f) => sel.has(f.relative_path))
    const remainingFiles = source.files.filter((f) => !sel.has(f.relative_path))

    const newGroup: EditableGroupState = {
      id: crypto.randomUUID(),
      author: source.author,
      variant_group_name: `${source.variant_group_name} (split)`,
      files: movedFiles,
      skip: false,
      status: 'pending',
      processed: 0,
      failed: 0,
      total: movedFiles.length,
    }

    const newGroups = [
      ...groups.map((g, i) =>
        i === sourceIndex ? { ...g, files: remainingFiles, total: remainingFiles.length } : g
      ),
      newGroup,
    ]
    setGroups(newGroups)
    setSelections((prev) => { const next = { ...prev }; delete next[sourceGroupId]; return next })
    setActiveTab(newGroups.length - 1)
  }

  // ── Save: single-group mode ────────────────────────────────────────

  const handleSaveSingleGroup = async () => {
    const gId = groupId ?? null
    if (gId === null || groups.length === 0) return
    setSaving(true)
    setSaveError(null)
    try {
      const kept = groups[0].files.filter((f) => !f.excluded)
      const payload: VariantGroupEditRequest = {
        base_name: groups[0].variant_group_name,
        author: groups[0].author || undefined,
        images: kept.map((f) => ({
          id: Number(f.relative_path),
          name: f.name,
          tags: f.tags,
          gridded: f.gridded,
          grid_width: f.grid_width,
          grid_height: f.grid_height,
          sub_variant: f.sub_variant,
        })),
        new_groups: groups.slice(1).map((g) => ({
          base_name: g.variant_group_name,
          author: g.author || undefined,
          image_ids: g.files.filter((f) => !f.excluded).map((f) => Number(f.relative_path)),
        })),
      }
      await variantGroupApi.edit(gId, payload)
      onSave()
      onClose()
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail ?? err?.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  // ── Save: mass-edit mode ───────────────────────────────────────────
  // Each group is an independent variant group; out-of-scope files are
  // preserved unchanged; in-scope files are saved with their edits.

  const handleSaveMassEdit = async () => {
    setSaving(true)
    setSaveError(null)
    const errors: string[] = []

    for (const group of groups) {
      const gId = Number(group.id)
      const kept = group.files.filter((f) => !f.excluded)
      try {
        await variantGroupApi.edit(gId, {
          base_name: group.variant_group_name,
          author: group.author || undefined,
          images: kept.map((f) => ({
            id: Number(f.relative_path),
            name: f.name,
            tags: f.tags,
            gridded: f.gridded,
            grid_width: f.grid_width,
            grid_height: f.grid_height,
            sub_variant: f.sub_variant,
          })),
          new_groups: [],
        })
      } catch (err: any) {
        errors.push(`${group.variant_group_name}: ${err?.response?.data?.detail ?? err?.message ?? 'failed'}`)
      }
    }

    setSaving(false)
    if (errors.length === 0) {
      onSave()
      onClose()
    } else {
      setSaveError(errors.join(' · '))
    }
  }

  // ── Delete group (single-group mode only) ──────────────────────────

  const handleDelete = async () => {
    const gId = groupId ?? null
    if (gId === null) return
    setSaving(true)
    try {
      await variantGroupApi.delete(gId)
      onSave()
      onClose()
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail ?? err?.message ?? 'Delete failed')
      setSaving(false)
      setConfirmingDelete(false)
    }
  }

  // ── Merge into another group (single-group mode only) ──────────────

  const handleMerge = async (targetGroup: { id: number }) => {
    const gId = groupId ?? null
    if (gId === null) return
    setMerging(true)
    try {
      await variantGroupApi.merge(gId, targetGroup.id)
      setShowMergePicker(false)
      onSave()
      onClose()
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail ?? err?.message ?? 'Merge failed')
      setMerging(false)
    }
  }

  // ── Derived values ─────────────────────────────────────────────────

  const isAllTab = activeTab === ALL_TAB
  const activeGroup = isAllTab ? null : groups[activeTab] ?? null
  const activeGroupId = isAllTab ? ALL_GROUP_ID : (activeGroup?.id ?? '')

  // All tab shows only in-scope files; per-group tab shows all (incl. out-of-scope for context)
  const allInScopeFiles = useMemo(() =>
    groups.flatMap((g) => g.files.filter((f) => !f.outOfScope)),
    [groups]
  )
  const perGroupFiles = activeGroup?.files ?? []
  const sourceFiles = isAllTab ? allInScopeFiles : perGroupFiles

  // Filtered files: for the in-scope section, filter normally; out-of-scope shown separately
  const inScopeSource = useMemo(() =>
    sourceFiles.filter((f) => !f.outOfScope),
    [sourceFiles]
  )
  const filteredInScope = useMemo(() => applyFileFilter(inScopeSource, fileFilter), [inScopeSource, fileFilter])
  const outOfScopeFiles = useMemo(() =>
    !isAllTab ? (activeGroup?.files ?? []).filter((f) => f.outOfScope) : [],
    [isAllTab, activeGroup]
  )

  const activeSelection = selections[activeGroupId] ?? new Set<string>()

  const groupSubVariants = useMemo(() => [...new Set(
    inScopeSource.filter((f) => !f.excluded && f.sub_variant).map((f) => f.sub_variant as string)
  )].sort(), [inScopeSource])

  const distinctSubVariants = useMemo(() => [...new Set(filteredInScope.map((f) => f.sub_variant))].sort((a, b) => {
    if (a === null) return -1
    if (b === null) return 1
    return (a ?? '').localeCompare(b ?? '')
  }), [filteredInScope])

  const showSubVariantHeadings = distinctSubVariants.length > 1
  const subVariantGroups = distinctSubVariants.map((sv) => ({
    subVariant: sv,
    files: filteredInScope.filter((f) => f.sub_variant === sv),
  }))

  const hasActiveFilter = fileFilter.text || fileFilter.active.length > 0
  const isOriginalGroup = !isAllTab && !isMassEdit && activeGroup?.id === String(groupId)

  const allSameAuthor = useMemo(() => {
    if (groups.length === 0) return ''
    const first = groups[0].author
    return groups.every((g) => g.author === first) ? first : ''
  }, [groups])

  const totalInScope = groups.reduce((s, g) => s + g.files.filter((f) => !f.outOfScope && !f.excluded).length, 0)

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !saving) onClose() }}>
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
                {totalInScope} image{totalInScope !== 1 ? 's' : ''} across {groups.length} group{groups.length !== 1 ? 's' : ''}
                {ungroupedCount > 0 && ` · ${ungroupedCount} ungrouped skipped`}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {/* Amber rule */}
        <div className="h-px bg-gradient-to-r from-primary/60 via-primary/20 to-transparent mx-6 shrink-0" />

        {/* Author datalist */}
        <datalist id="author-suggestions-edit">
          {authorSuggestions.map((a) => <option key={a} value={a} />)}
        </datalist>

        {/* ── Loading ── */}
        {loading && (
          <div className="flex items-center justify-center flex-1">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {/* ── Load error ── */}
        {!loading && loadError && (
          <div className="mx-6 mt-4 flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />{loadError}
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
                      {groups.reduce((s, g) => s + g.files.filter((f) => !f.excluded && !f.outOfScope).length, 0)}
                    </span>
                  </button>
                  <div className="h-px bg-border/30 mx-3 my-0.5" />

                  {groups.map((g, i) => (
                    <button
                      key={g.id}
                      onClick={() => setActiveTab(i)}
                      className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 min-w-0 ${
                        activeTab === i
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                      }`}
                    >
                      <span className="flex-1 text-[12px] truncate">{g.variant_group_name}</span>
                      <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
                        {g.files.filter((f) => !f.excluded && !f.outOfScope).length}
                        {g.files.some((f) => f.outOfScope) && (
                          <span className="ml-0.5 opacity-50">+{g.files.filter((f) => f.outOfScope).length}</span>
                        )}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* ── Right: active group content ── */}
            <div className="flex-1 min-w-0 flex flex-col overflow-hidden">

              {/* Group metadata */}
              <div className="px-5 pt-4 pb-3 border-b border-border/30 shrink-0">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1.5 block font-semibold">
                      Author
                    </label>
                    <input
                      value={isAllTab ? allSameAuthor : (activeGroup?.author ?? '')}
                      onChange={(e) => {
                        if (isAllTab) {
                          setGroups((prev) => prev.map((g) => ({ ...g, author: e.target.value })))
                        } else {
                          updateGroup(activeTab, { author: e.target.value })
                        }
                      }}
                      placeholder={isAllTab && !allSameAuthor ? 'Multiple — type to set for all groups' : 'Author name'}
                      list="author-suggestions-edit"
                      className="w-full h-8 px-3 text-sm rounded border border-border bg-secondary text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors"
                    />
                    {isMassEdit && (
                      <p className="text-[10px] text-muted-foreground/40 mt-1">
                        Applies to all images in {isAllTab ? 'each' : 'this'} group
                      </p>
                    )}
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1.5 block font-semibold">
                      Group Name
                    </label>
                    <input
                      value={isAllTab ? '' : (activeGroup?.variant_group_name ?? '')}
                      onChange={(e) => !isAllTab && updateGroup(activeTab, { variant_group_name: e.target.value })}
                      placeholder={isAllTab ? '— (select a group to rename)' : 'Group name'}
                      disabled={isAllTab}
                      className="w-full h-8 px-3 text-sm rounded border border-border bg-secondary text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    />
                    {isMassEdit && (
                      <p className="text-[10px] text-muted-foreground/40 mt-1">
                        Applies to all images in {isAllTab ? 'each' : 'this'} group
                      </p>
                    )}
                  </div>
                </div>
              </div>

              {/* File toolbar */}
              <div className="px-5">
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
                  onBulkSetGrid={(v) => bulkSetGrid(isAllTab ? null : activeGroupId, v)}
                  onBulkSetSubVariant={(v) => bulkSetSubVariant(isAllTab ? null : activeGroupId, v)}
                  onBulkExclude={() => bulkExclude(isAllTab ? null : activeGroupId)}
                  onMoveToNewGroup={!isAllTab && !isMassEdit && activeGroup?.id ? () => moveToNewGroup(activeGroup.id) : undefined}
                  excludeLabel={isMassEdit ? 'Remove' : 'Delete'}
                />
              </div>

              {/* File gallery */}
              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
                {showSubVariantHeadings ? (
                  subVariantGroups.map((svGroup) => {
                    const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
                    const isEditing = !isAllTab && editingSvHeading === svGroup.subVariant && svGroup.subVariant !== null
                    return (
                      <div key={svGroup.subVariant ?? '__main__'} className="mb-2">
                        <div className="flex items-center gap-2 py-1.5 mt-2 first:mt-0">
                          {isEditing ? (
                            <input
                              value={svHeadingDraft}
                              autoFocus
                              onChange={(e) => setSvHeadingDraft(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  renameSubVariant(activeGroup!.id, svGroup.subVariant!, svHeadingDraft)
                                  setEditingSvHeading(null)
                                }
                                if (e.key === 'Escape') setEditingSvHeading(null)
                              }}
                              onBlur={() => {
                                renameSubVariant(activeGroup!.id, svGroup.subVariant!, svHeadingDraft)
                                setEditingSvHeading(null)
                              }}
                              className="text-[11px] font-semibold text-foreground border-b border-primary/70 bg-transparent outline-none uppercase tracking-wider capitalize"
                            />
                          ) : (
                            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider capitalize whitespace-nowrap">
                              {svGroup.subVariant ?? 'Main'}
                            </span>
                          )}
                          {!isAllTab && svGroup.subVariant !== null && !isEditing && (
                            <button
                              onClick={() => { setSvHeadingDraft(svGroup.subVariant!); setEditingSvHeading(svGroup.subVariant!) }}
                              className="text-muted-foreground/40 hover:text-muted-foreground transition-colors"
                              title={`Rename "${svGroup.subVariant}"`}
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                          )}
                          <div className="flex-1 h-px bg-border/30" />
                          <span className="text-[11px] text-muted-foreground/40 tabular-nums">{nonExcluded}</span>
                          {!isAllTab && svGroup.subVariant !== null && !isEditing && (
                            <button
                              onClick={() => clearSubVariantLabel(activeGroup!.id, svGroup.subVariant!)}
                              className="text-muted-foreground/40 hover:text-primary transition-colors"
                              title={`Remove "${svGroup.subVariant}" label from all files`}
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                        <div className="space-y-1.5 pb-2">
                          {svGroup.files.map((file) => (
                            <FileCard
                              key={file.relative_path}
                              file={file}
                              jobId=""
                              vocab={tagVocab}
                              existingSubVariants={groupSubVariants}
                              selected={activeSelection.has(file.relative_path)}
                              onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
                              onUpdate={(updates) =>
                                isAllTab
                                  ? updateFileAnyGroup(file.relative_path, updates)
                                  : updateFile(activeTab, file.relative_path, updates)
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
                        existingSubVariants={groupSubVariants}
                        selected={activeSelection.has(file.relative_path)}
                        onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
                        onUpdate={(updates) =>
                          isAllTab
                            ? updateFileAnyGroup(file.relative_path, updates)
                            : updateFile(activeTab, file.relative_path, updates)
                        }
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
                          existingSubVariants={groupSubVariants}
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

                {/* Save / Cancel */}
                <div className="flex items-center gap-2">
                  {saveError && (
                    <span className="text-xs text-destructive flex items-center gap-1 max-w-xs truncate">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0" />{saveError}
                    </span>
                  )}
                  <button
                    onClick={onClose}
                    disabled={saving}
                    className="px-3 py-1.5 text-sm rounded border border-border bg-secondary text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={isMassEdit ? handleSaveMassEdit : handleSaveSingleGroup}
                    disabled={saving}
                    className="px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40"
                  >
                    {saving
                      ? <><Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />Saving…</>
                      : isMassEdit
                        ? `Save Changes (${groups.length} group${groups.length !== 1 ? 's' : ''})`
                        : 'Save'
                    }
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </DialogContent>

      {/* Merge picker — rendered as sibling dialog so it layers on top */}
      <MergeGroupPicker
        open={showMergePicker}
        onClose={() => setShowMergePicker(false)}
        excludeGroupId={groupId}
        onSelect={handleMerge}
      />
    </Dialog>
  )
}
