import { useState, useEffect, useCallback } from 'react'
import {
  AlertCircle,
  Loader2,
  X,
  Trash2,
  Search,
  Pencil,
} from 'lucide-react'
import { variantGroupApi, tagApi, imageApi, getThumbnailUrlById, getImageUrlById } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type {
  EditableFileState,
  EditableGroupState,
  TagData,
  Image,
  VariantGroupEditRequest,
} from '@/types'
import { FileCard } from './import/FileCard'
import { FileToolbar } from './import/FileToolbar'
import { parseTagVocabulary } from './import/types'
import type { ParsedTagVocab } from './import/types'
import { EMPTY_FILTER, applyFileFilter } from './import/fileFilter'
import type { FileFilter } from './import/fileFilter'

interface EditGroupDialogProps {
  groupId: number | null
  open: boolean
  onClose: () => void
  onSave: () => void
}

function imageToEditable(img: Image): EditableFileState {
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
    previewUrl: getThumbnailUrlById(img.id),
    fullImageUrl: getImageUrlById(img.id),
  }
}

export function EditGroupDialog({ groupId, open, onClose, onSave }: EditGroupDialogProps) {
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const [groups, setGroups] = useState<EditableGroupState[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [tagVocab, setTagVocab] = useState<ParsedTagVocab[]>([])
  const [selections, setSelections] = useState<Record<string, Set<string>>>({})
  const [fileFilter, setFileFilter] = useState<FileFilter>(EMPTY_FILTER)
  const [authorSuggestions, setAuthorSuggestions] = useState<string[]>([])

  // Sub-variant heading inline rename state
  const [editingSvHeading, setEditingSvHeading] = useState<string | null>(null)
  const [svHeadingDraft, setSvHeadingDraft] = useState('')

  // Reset state when dialog closes
  const reset = useCallback(() => {
    setLoading(false)
    setLoadError(null)
    setSaving(false)
    setSaveError(null)
    setConfirmingDelete(false)
    setGroups([])
    setActiveTab(0)
    setSelections({})
    setFileFilter(EMPTY_FILTER)
    setEditingSvHeading(null)
  }, [])

  // Clear filter on tab change
  useEffect(() => { setFileFilter(EMPTY_FILTER) }, [activeTab])

  // Load data when dialog opens
  useEffect(() => {
    if (!open || groupId === null) { reset(); return }

    setLoading(true)
    setLoadError(null)

    Promise.all([
      variantGroupApi.get(groupId),
      tagApi.getCategories(),
      imageApi.getAuthors(),
    ]).then(([group, categories, authors]) => {
      setGroups([{
        id: String(group.id),
        author: group.author ?? '',
        variant_group_name: group.base_name,
        files: group.images.map(imageToEditable),
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
  }, [open, groupId, reset])

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
      visibleFiles.filter((f) => !f.excluded).forEach((f) => set.add(f.relative_path))
      return { ...prev, [gId]: set }
    })
  }

  const deselectAll = (gId: string) => {
    setSelections((prev) => ({ ...prev, [gId]: new Set<string>() }))
  }

  // ── Bulk actions ───────────────────────────────────────────────────

  const bulkAddTag = (gId: string, tag: TagData) => {
    const sel = selections[gId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) => {
            if (!sel.has(f.relative_path) || f.excluded) return f
            if (f.tags.some((t) => t.category === tag.category && t.value === tag.value)) return f
            return { ...f, tags: [...f.tags, tag] }
          }),
        }
      })
    )
  }

  const bulkSetGrid = (gId: string, value: boolean | null) => {
    const sel = selections[gId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) => {
            if (!sel.has(f.relative_path) || f.excluded) return f
            return { ...f, gridded: value }
          }),
        }
      })
    )
  }

  const bulkSetSubVariant = (gId: string, value: string) => {
    const sel = selections[gId] ?? new Set<string>()
    const normalized = value.trim() || null
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) => {
            if (!sel.has(f.relative_path) || f.excluded) return f
            return { ...f, sub_variant: normalized }
          }),
        }
      })
    )
  }

  const bulkExclude = (gId: string) => {
    const sel = selections[gId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== gId) return g
        return { ...g, files: g.files.map((f) => (!sel.has(f.relative_path) ? f : { ...f, excluded: true })) }
      })
    )
    deselectAll(gId)
  }

  const clearSubVariantLabel = (gId: string, subVariant: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== gId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            f.sub_variant === subVariant && !f.excluded ? { ...f, sub_variant: null } : f
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
            f.sub_variant === oldVal && !f.excluded ? { ...f, sub_variant: newVal.trim() || null } : f
          ),
        }
      })
    )
  }

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

  // ── Save ───────────────────────────────────────────────────────────

  const handleSave = async () => {
    if (groupId === null || groups.length === 0) return
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
      await variantGroupApi.edit(groupId, payload)
      onSave()
      onClose()
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail ?? err?.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  // ── Delete group ───────────────────────────────────────────────────

  const handleDelete = async () => {
    if (groupId === null) return
    setSaving(true)
    try {
      await variantGroupApi.delete(groupId)
      onSave()
      onClose()
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail ?? err?.message ?? 'Delete failed')
      setSaving(false)
      setConfirmingDelete(false)
    }
  }

  // ── Derived values ─────────────────────────────────────────────────

  const activeGroup = groups[activeTab]
  const activeSelection = selections[activeGroup?.id ?? ''] ?? new Set<string>()
  const filteredFiles = activeGroup ? applyFileFilter(activeGroup.files, fileFilter) : []

  const groupSubVariants = [...new Set(
    activeGroup?.files.filter((f) => !f.excluded && f.sub_variant).map((f) => f.sub_variant as string) ?? []
  )].sort()

  const distinctSubVariants = [...new Set(filteredFiles.map((f) => f.sub_variant))].sort((a, b) => {
    if (a === null) return -1
    if (b === null) return 1
    return (a ?? '').localeCompare(b ?? '')
  })
  const showSubVariantHeadings = distinctSubVariants.length > 1
  const subVariantGroups = distinctSubVariants.map((sv) => ({
    subVariant: sv,
    files: filteredFiles.filter((f) => f.sub_variant === sv),
  }))

  const hasActiveFilter = fileFilter.text || fileFilter.active.length > 0

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !saving) onClose() }}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>Edit Group</DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        )}

        {!loading && loadError && (
          <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />{loadError}
          </div>
        )}

        {!loading && !loadError && activeGroup && (
          <div className="flex flex-col gap-3 min-h-0 flex-1">
            {/* Author datalist */}
            <datalist id="author-suggestions-edit">
              {authorSuggestions.map((a) => <option key={a} value={a} />)}
            </datalist>

            {/* Tab bar for split groups */}
            {groups.length > 1 && (
              <div className="flex items-center gap-1 border-b border-slate-200 overflow-x-auto flex-shrink-0 -mx-1 px-1">
                {groups.map((g, i) => (
                  <button
                    key={g.id}
                    onClick={() => setActiveTab(i)}
                    className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-all flex items-center gap-1.5
                      ${i === activeTab ? 'border-emerald-600 text-emerald-700 font-medium' : 'border-transparent text-slate-400 hover:text-slate-600'}`}
                  >
                    <span>{g.variant_group_name}</span>
                    <span className="text-[11px] text-slate-300 font-normal">
                      {g.files.filter((f) => !f.excluded).length}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {/* Group metadata */}
            <div className="grid grid-cols-2 gap-3 flex-shrink-0">
              <div>
                <label className="text-[11px] font-semibold text-slate-400 mb-1 block uppercase tracking-wider">Author</label>
                <Input
                  value={activeGroup.author}
                  onChange={(e) => updateGroup(activeTab, { author: e.target.value })}
                  placeholder="Author name"
                  list="author-suggestions-edit"
                />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-400 mb-1 block uppercase tracking-wider">Group Name</label>
                <Input
                  value={activeGroup.variant_group_name}
                  onChange={(e) => updateGroup(activeTab, { variant_group_name: e.target.value })}
                  placeholder="Group name"
                />
              </div>
            </div>

            {/* File toolbar */}
            <FileToolbar
              files={activeGroup.files}
              filteredFiles={filteredFiles}
              selection={activeSelection}
              filter={fileFilter}
              vocab={tagVocab}
              onFilterChange={setFileFilter}
              onSelectAll={() => selectAllVisible(activeGroup.id, filteredFiles)}
              onDeselectAll={() => deselectAll(activeGroup.id)}
              onBulkAddTag={(tag) => bulkAddTag(activeGroup.id, tag)}
              onBulkSetGrid={(v) => bulkSetGrid(activeGroup.id, v)}
              onBulkSetSubVariant={(v) => bulkSetSubVariant(activeGroup.id, v)}
              onBulkExclude={() => bulkExclude(activeGroup.id)}
              onMoveToNewGroup={() => moveToNewGroup(activeGroup.id)}
              excludeLabel="Delete"
            />

            {/* File gallery */}
            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              {showSubVariantHeadings ? (
                subVariantGroups.map((svGroup) => {
                  const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
                  const isEditingThis = editingSvHeading === svGroup.subVariant && svGroup.subVariant !== null
                  return (
                    <div key={svGroup.subVariant ?? '__main__'} className="mb-1">
                      <div className="flex items-center gap-2 py-1.5 px-1 sticky top-0 bg-white z-10">
                        {isEditingThis ? (
                          <input
                            value={svHeadingDraft}
                            autoFocus
                            onChange={(e) => setSvHeadingDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                renameSubVariant(activeGroup.id, svGroup.subVariant!, svHeadingDraft)
                                setEditingSvHeading(null)
                              }
                              if (e.key === 'Escape') setEditingSvHeading(null)
                            }}
                            onBlur={() => {
                              renameSubVariant(activeGroup.id, svGroup.subVariant!, svHeadingDraft)
                              setEditingSvHeading(null)
                            }}
                            className="text-[11px] font-semibold text-slate-600 border-b border-emerald-300 bg-transparent outline-none uppercase tracking-wider capitalize"
                          />
                        ) : (
                          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider capitalize whitespace-nowrap">
                            {svGroup.subVariant ?? 'Main'}
                          </span>
                        )}
                        {svGroup.subVariant !== null && !isEditingThis && (
                          <button
                            onClick={() => { setSvHeadingDraft(svGroup.subVariant!); setEditingSvHeading(svGroup.subVariant!) }}
                            className="text-slate-300 hover:text-slate-500 transition-colors"
                            title={`Rename "${svGroup.subVariant}"`}
                          >
                            <Pencil className="h-3 w-3" />
                          </button>
                        )}
                        <div className="flex-1 h-px bg-slate-100" />
                        <span className="text-[11px] text-slate-300 tabular-nums">{nonExcluded}</span>
                        {svGroup.subVariant !== null && !isEditingThis && (
                          <button
                            onClick={() => clearSubVariantLabel(activeGroup.id, svGroup.subVariant!)}
                            className="text-slate-300 hover:text-amber-500 transition-colors"
                            title={`Remove "${svGroup.subVariant}" label from all files`}
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                      <div className="space-y-2 pb-2">
                        {svGroup.files.map((file) => (
                          <FileCard
                            key={file.relative_path}
                            file={file}
                            jobId=""
                            vocab={tagVocab}
                            existingSubVariants={groupSubVariants}
                            selected={activeSelection.has(file.relative_path)}
                            onToggleSelect={() => toggleFileSelection(activeGroup.id, file.relative_path)}
                            onUpdate={(updates) => updateFile(activeTab, file.relative_path, updates)}
                          />
                        ))}
                      </div>
                    </div>
                  )
                })
              ) : (
                <div className="space-y-2">
                  {filteredFiles.map((file) => (
                    <FileCard
                      key={file.relative_path}
                      file={file}
                      jobId=""
                      vocab={tagVocab}
                      existingSubVariants={groupSubVariants}
                      selected={activeSelection.has(file.relative_path)}
                      onToggleSelect={() => toggleFileSelection(activeGroup.id, file.relative_path)}
                      onUpdate={(updates) => updateFile(activeTab, file.relative_path, updates)}
                    />
                  ))}
                </div>
              )}
              {filteredFiles.length === 0 && hasActiveFilter && (
                <div className="flex flex-col items-center py-12 text-slate-400 gap-2">
                  <Search className="h-8 w-8 text-slate-200" />
                  <p className="text-sm">No files match the current filter</p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between flex-shrink-0 pt-3 border-t border-slate-100 gap-3">
              {/* Delete group */}
              {activeTab === 0 && (
                confirmingDelete ? (
                  <div className="flex items-center gap-2 text-sm text-red-600">
                    <span>Delete this group and all its images?</span>
                    <Button size="sm" variant="destructive" onClick={handleDelete} disabled={saving}>
                      {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Confirm'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmingDelete(false)} disabled={saving}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-red-400 hover:text-red-600 hover:bg-red-50 gap-1.5"
                    onClick={() => setConfirmingDelete(true)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete Group
                  </Button>
                )
              )}
              {activeTab !== 0 && <div />}

              {/* Save / Cancel */}
              <div className="flex items-center gap-2">
                {saveError && (
                  <span className="text-xs text-red-500 flex items-center gap-1">
                    <AlertCircle className="h-3.5 w-3.5" />{saveError}
                  </span>
                )}
                <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>Cancel</Button>
                <Button
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? <><Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />Saving…</> : 'Save'}
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
