import { useState, useRef, useCallback, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Upload,
  Check,
  AlertCircle,
  Loader2,
  X,
  MoreHorizontal,
  SkipForward,
  Merge,
  Undo2,
  UserRound,
  FolderOpen,
  Search,
  Pencil,
} from 'lucide-react'
import { importApi, tagApi, imageApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type {
  ImportUploadResponse,
  EditableFileState,
  EditableGroupState,
  TagData,
  ImportConfirmFile,
} from '@/types'
import { FileCard } from './import/FileCard'
import { FileToolbar } from './import/FileToolbar'
import { parseTagVocabulary, humanizeFilename } from './import/types'
import type { ParsedTagVocab } from './import/types'
import { EMPTY_FILTER, applyFileFilter } from './import/fileFilter'
import type { FileFilter } from './import/fileFilter'

type DialogState = 'upload' | 'preview' | 'processing' | 'done'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onActiveChange?: (active: boolean) => void
}

export function ImportDialog({ open, onOpenChange, onActiveChange }: ImportDialogProps) {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const blobUrlsRef = useRef<string[]>([])

  const [state, setState] = useState<DialogState>('upload')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [groups, setGroups] = useState<EditableGroupState[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [defaultAuthor, setDefaultAuthor] = useState('')
  const [tagVocab, setTagVocab] = useState<ParsedTagVocab[]>([])
  const [selections, setSelections] = useState<Record<string, Set<string>>>({})
  const [fileFilter, setFileFilter] = useState<FileFilter>(EMPTY_FILTER)
  const [authorSuggestions, setAuthorSuggestions] = useState<string[]>([])
  const [editingSvHeading, setEditingSvHeading] = useState<string | null>(null)
  const [svHeadingDraft, setSvHeadingDraft] = useState('')

  useEffect(() => { onActiveChange?.(state === 'processing') }, [state, onActiveChange])

  // Clear filter when switching tabs
  useEffect(() => { setFileFilter(EMPTY_FILTER); setEditingSvHeading(null) }, [activeTab])

  // Status polling during processing
  useEffect(() => {
    if (state !== 'processing' || !jobId) return

    const poll = async () => {
      try {
        const status = await importApi.status(jobId)
        setGroups((prev) =>
          prev.map((g) => {
            const gs = status.groups.find((s) => s.variant_group_name === g.variant_group_name)
            if (!gs) return g
            return {
              ...g,
              status: gs.status as EditableGroupState['status'],
              processed: gs.processed_files,
              failed: gs.failed_files,
              total: gs.total_files || g.total,
            }
          })
        )
        if (
          status.groups.length > 0 &&
          status.groups.every((gs) => gs.status === 'completed' || gs.status === 'failed')
        ) {
          setState('done')
        }
      } catch { /* ignore transient poll errors */ }
    }

    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [state, jobId])

  // Fetch tag vocab + author suggestions on entering preview
  useEffect(() => {
    if (state !== 'preview') return
    if (tagVocab.length === 0) {
      tagApi.getCategories().then((cats) => setTagVocab(parseTagVocabulary(cats))).catch(() => {})
    }
    if (authorSuggestions.length === 0) {
      imageApi.getAuthors().then(setAuthorSuggestions).catch(() => {})
    }
  }, [state]) // eslint-disable-line react-hooks/exhaustive-deps

  const reset = useCallback(() => {
    blobUrlsRef.current.forEach((url) => URL.revokeObjectURL(url))
    blobUrlsRef.current = []
    setState('upload')
    setUploading(false)
    setUploadError(null)
    setJobId(null)
    setGroups([])
    setActiveTab(0)
    setDefaultAuthor('')
    setTagVocab([])
    setSelections({})
    setFileFilter(EMPTY_FILTER)
    setEditingSvHeading(null)
    setAuthorSuggestions([])
  }, [])

  const handleClose = useCallback(() => {
    if (state === 'processing') { onOpenChange(false); return }
    if (state === 'done') {
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['search'] })
    }
    reset()
    onOpenChange(false)
  }, [state, queryClient, reset, onOpenChange])

  // ── Upload ────────────────────────────────────────────────────────

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    setUploading(true)
    setUploadError(null)

    try {
      const relativePaths: string[] = []
      const blobUrlMap: Record<string, string> = {}
      for (let i = 0; i < files.length; i++) {
        const relPath = (files[i] as any).webkitRelativePath || files[i].name
        relativePaths.push(relPath)
        const blobUrl = URL.createObjectURL(files[i])
        blobUrlMap[relPath] = blobUrl
        blobUrlsRef.current.push(blobUrl)
      }

      const response: ImportUploadResponse = await importApi.upload(files, relativePaths)
      setJobId(response.job_id)

      const editableGroups: EditableGroupState[] = response.variant_groups.map((vg) => ({
        id: crypto.randomUUID(),
        author: vg.author || '',
        variant_group_name: vg.variant_group_name,
        files: vg.files.map((f) => ({
          relative_path: f.relative_path,
          filename: f.filename,
          name: humanizeFilename(f.filename),
          tags: [...f.detected_tags],
          gridded: f.gridded,
          grid_width: f.grid_width,
          grid_height: f.grid_height,
          sub_variant: f.sub_variant,
          excluded: false,
          previewUrl: blobUrlMap[f.relative_path],
        })),
        skip: false,
        status: 'pending',
        processed: 0,
        failed: 0,
        total: vg.files.length,
      }))

      setGroups(editableGroups)
      setState('preview')
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || err?.message || 'Upload failed')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  // ── Group / file state helpers ────────────────────────────────────

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

  const mergeGroups = (sourceIndex: number, targetIndex: number) => {
    setGroups((prev) => {
      const source = prev[sourceIndex]
      const target = prev[targetIndex]
      if (!source || !target) return prev
      return prev
        .map((g, i) => {
          if (i === targetIndex) return { ...g, files: [...g.files, ...source.files], total: g.files.length + source.files.length }
          return g
        })
        .filter((_, i) => i !== sourceIndex)
    })
    setActiveTab((prev) => {
      if (sourceIndex < prev) return prev - 1
      if (sourceIndex === prev) return Math.min(targetIndex, groups.length - 2)
      return prev
    })
  }

  const applyDefaultAuthor = () => {
    if (!defaultAuthor.trim()) return
    setGroups((prev) => prev.map((g) => (g.author === '' ? { ...g, author: defaultAuthor.trim() } : g)))
  }

  // ── Selection helpers ─────────────────────────────────────────────

  const toggleFileSelection = (groupId: string, relativePath: string) => {
    setSelections((prev) => {
      const set = new Set(prev[groupId] ?? [])
      if (set.has(relativePath)) set.delete(relativePath)
      else set.add(relativePath)
      return { ...prev, [groupId]: set }
    })
  }

  const selectAllVisible = (groupId: string, visibleFiles: EditableFileState[]) => {
    setSelections((prev) => {
      const set = new Set<string>(prev[groupId] ?? [])
      visibleFiles.filter((f) => !f.excluded).forEach((f) => set.add(f.relative_path))
      return { ...prev, [groupId]: set }
    })
  }

  const deselectAll = (groupId: string) => {
    setSelections((prev) => ({ ...prev, [groupId]: new Set<string>() }))
  }

  // ── Bulk actions ──────────────────────────────────────────────────

  const bulkAddTag = (groupId: string, tag: TagData) => {
    const sel = selections[groupId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
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

  const bulkSetGrid = (groupId: string, value: boolean | null) => {
    const sel = selections[groupId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
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

  const bulkSetSubVariant = (groupId: string, value: string) => {
    const sel = selections[groupId] ?? new Set<string>()
    const normalized = value.trim() || null
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
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

  const bulkExclude = (groupId: string) => {
    const sel = selections[groupId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
        return { ...g, files: g.files.map((f) => (!sel.has(f.relative_path) ? f : { ...f, excluded: true })) }
      })
    )
    deselectAll(groupId)
  }

  // Remove the sub-variant label from all non-excluded files that have the given sub_variant,
  // effectively merging them into the "Main" (null sub-variant) group.
  const clearSubVariantLabel = (groupId: string, subVariant: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            f.sub_variant === subVariant && !f.excluded ? { ...f, sub_variant: null } : f
          ),
        }
      })
    )
  }

  const renameSubVariant = (groupId: string, oldVal: string, newVal: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
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

  // ── Confirm ───────────────────────────────────────────────────────

  const buildConfirmFiles = (group: EditableGroupState): ImportConfirmFile[] =>
    group.files
      .filter((f) => !f.excluded)
      .map((f) => ({
        relative_path: f.relative_path,
        name: f.name,
        tags: f.tags,
        gridded: f.gridded,
        grid_width: f.grid_width,
        grid_height: f.grid_height,
        sub_variant: f.sub_variant,
      }))

  const handleConfirmGroup = async (index: number) => {
    if (!jobId) return
    const group = groups[index]
    if (group.skip) return
    const confirmFiles = buildConfirmFiles(group)
    if (confirmFiles.length === 0) return

    updateGroup(index, { status: 'running' })
    setState('processing')
    try {
      await importApi.confirm(jobId, {
        author: group.author,
        variant_group_name: group.variant_group_name,
        files: confirmFiles,
      })
    } catch {
      updateGroup(index, { status: 'failed' })
    }
  }

  const handleConfirmAll = async () => {
    if (!jobId) return
    setState('processing')

    // Build the list of groups with files to submit.
    const toSubmit: { i: number; author: string; variant_group_name: string; files: ImportConfirmFile[] }[] = []
    groups.forEach((group, i) => {
      if (group.status !== 'pending' || group.skip) return
      const confirmFiles = buildConfirmFiles(group)
      if (confirmFiles.length === 0) { updateGroup(i, { status: 'completed', processed: 0 }); return }
      toSubmit.push({ i, author: group.author, variant_group_name: group.variant_group_name, files: confirmFiles })
    })

    if (toSubmit.length === 0) return
    toSubmit.forEach(({ i }) => updateGroup(i, { status: 'running' }))

    // Single request → single Prefect flow run → CLIP loaded once for all groups.
    try {
      await importApi.confirmAll(
        jobId,
        toSubmit.map(({ author, variant_group_name, files }) => ({ author, variant_group_name, files })),
      )
    } catch {
      toSubmit.forEach(({ i }) => updateGroup(i, { status: 'failed' }))
    }
  }

  // ── Derived values ────────────────────────────────────────────────

  const activeGroup = groups[activeTab]
  const activeSelection = selections[activeGroup?.id ?? ''] ?? new Set<string>()
  const filteredFiles = activeGroup ? applyFileFilter(activeGroup.files, fileFilter) : []

  // All distinct non-empty sub-variants in the active group (for pickers in FileCard/FileToolbar).
  const groupSubVariants = [...new Set(
    activeGroup?.files.filter((f) => !f.excluded && f.sub_variant).map((f) => f.sub_variant as string) ?? []
  )].sort()

  // Group filtered files by sub_variant for gallery rendering.
  // null sub_variant = "Main" group, always first; others sorted alphabetically.
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

  const pendingGroups = groups.filter((g) => g.status === 'pending' && !g.skip)
  const completedCount = groups.filter((g) => g.status === 'completed').length
  const totalFiles = groups.reduce((sum, g) => sum + g.files.length, 0)
  const hasEmptyAuthors = groups.some((g) => !g.skip && g.author === '' && g.status === 'pending')

  // ── Render ────────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className={`${state === 'preview' || state === 'processing' ? 'max-w-5xl' : 'max-w-lg'} max-h-[85vh] overflow-hidden flex flex-col`}
        onClose={handleClose}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {state === 'upload' && <><Upload className="h-5 w-5 text-emerald-600" />Import Battlemaps</>}
            {state === 'preview' && <><FolderOpen className="h-5 w-5 text-emerald-600" />Review Import</>}
            {state === 'processing' && <><Loader2 className="h-5 w-5 text-emerald-600 animate-spin" />Processing…</>}
            {state === 'done' && <><Check className="h-5 w-5 text-emerald-600" />Import Complete</>}
          </DialogTitle>
        </DialogHeader>

        {/* ── Upload ──────────────────────────────────────────────── */}
        {state === 'upload' && (
          <div className="space-y-5">
            <p className="text-sm text-muted-foreground">
              Select image files, a folder, or a .zip archive to import.
            </p>
            <div className="flex gap-3">
              <input ref={fileInputRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.zip"
                onChange={handleFileSelect} className="hidden" id="import-files" />
              <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}
                className="bg-emerald-600 hover:bg-emerald-700 text-white">
                {uploading
                  ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Analysing…</>
                  : <><Upload className="h-4 w-4 mr-2" />Select Files</>
                }
              </Button>
              <input type="file"
                // @ts-expect-error webkitdirectory is not in HTMLInputElement type
                webkitdirectory="" multiple onChange={handleFileSelect} className="hidden" id="import-folder" />
              <Button variant="outline" onClick={() => document.getElementById('import-folder')?.click()} disabled={uploading}>
                <FolderOpen className="h-4 w-4 mr-2" />Select Folder
              </Button>
            </div>
            {uploadError && (
              <div className="flex items-center gap-2 text-destructive text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />{uploadError}
              </div>
            )}
          </div>
        )}

        {/* ── Preview / Processing ─────────────────────────────────── */}
        {(state === 'preview' || state === 'processing') && groups.length > 0 && (
          <div className="flex flex-col gap-3 min-h-0 flex-1">
            {/* Author datalist for autocomplete */}
            <datalist id="author-suggestions">
              {authorSuggestions.map((a) => <option key={a} value={a} />)}
            </datalist>

            <p className="text-sm text-slate-500 flex-shrink-0">
              {totalFiles} files in {groups.length} group{groups.length !== 1 ? 's' : ''}. Review metadata, then import.
            </p>

            {/* Default author bar */}
            {hasEmptyAuthors && (
              <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-2.5 flex-shrink-0">
                <UserRound className="h-4 w-4 text-amber-500 flex-shrink-0" />
                <span className="text-sm text-amber-700 flex-shrink-0">Missing author</span>
                <Input
                  value={defaultAuthor}
                  onChange={(e) => setDefaultAuthor(e.target.value)}
                  placeholder="Enter default author…"
                  list="author-suggestions"
                  className="h-8 text-sm max-w-[200px] bg-white"
                />
                <Button size="sm" variant="outline" onClick={applyDefaultAuthor}
                  disabled={!defaultAuthor.trim()} className="flex-shrink-0 h-8 text-xs">
                  Apply to All
                </Button>
              </div>
            )}

            {/* Tab bar */}
            {groups.length > 1 && (
              <div className="flex items-center gap-1 border-b border-slate-200 overflow-x-auto flex-shrink-0 -mx-1 px-1">
                {groups.map((g, i) => (
                  <div key={g.id} className="flex items-center">
                    <button
                      onClick={() => setActiveTab(i)}
                      className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-all flex items-center gap-1.5
                        ${i === activeTab ? 'border-emerald-600 text-emerald-700 font-medium' : 'border-transparent text-slate-400 hover:text-slate-600'}
                        ${g.skip ? 'opacity-40' : ''}`}
                    >
                      {g.status === 'completed' && <Check className="h-3 w-3 text-emerald-500" />}
                      {g.status === 'running' && <Loader2 className="h-3 w-3 animate-spin text-emerald-500" />}
                      {g.status === 'failed' && <AlertCircle className="h-3 w-3 text-red-400" />}
                      {g.skip && <SkipForward className="h-3 w-3" />}
                      <span className={g.skip ? 'line-through' : ''}>{g.variant_group_name}</span>
                      <span className="text-[11px] text-slate-300 font-normal">
                        {g.files.filter((f) => !f.excluded).length}
                      </span>
                    </button>

                    {g.status === 'pending' && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button className="p-0.5 rounded hover:bg-slate-100 transition-colors -ml-0.5">
                            <MoreHorizontal className="h-3.5 w-3.5 text-slate-300" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          <DropdownMenuItem onClick={() => updateGroup(i, { skip: !g.skip })}>
                            <SkipForward className="h-4 w-4 mr-2" />
                            {g.skip ? 'Unskip Group' : 'Skip Group'}
                          </DropdownMenuItem>
                          {groups.length > 1 && (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuLabel className="text-xs text-slate-400">Merge into…</DropdownMenuLabel>
                              {groups.map((target, j) =>
                                j !== i ? (
                                  <DropdownMenuItem key={target.id} onClick={() => mergeGroups(i, j)}>
                                    <Merge className="h-4 w-4 mr-2" />{target.variant_group_name}
                                  </DropdownMenuItem>
                                ) : null
                              )}
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Active group */}
            {activeGroup && (
              <div className="flex flex-col gap-3 min-h-0 flex-1">
                {activeGroup.skip ? (
                  <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-3">
                    <SkipForward className="h-10 w-10 text-slate-200" />
                    <p className="text-sm font-medium">Group skipped</p>
                    <button onClick={() => updateGroup(activeTab, { skip: false })}
                      className="inline-flex items-center gap-1.5 text-sm text-emerald-600 hover:text-emerald-700 font-medium transition-colors">
                      <Undo2 className="h-3.5 w-3.5" />Undo
                    </button>
                  </div>
                ) : (
                  <>
                    {/* Group metadata */}
                    <div className="grid grid-cols-2 gap-3 flex-shrink-0">
                      <div>
                        <label className="text-[11px] font-semibold text-slate-400 mb-1 block uppercase tracking-wider">Author</label>
                        <Input
                          value={activeGroup.author}
                          onChange={(e) => updateGroup(activeTab, { author: e.target.value })}
                          placeholder="Author name"
                          list="author-suggestions"
                          disabled={activeGroup.status !== 'pending'}
                          className={!activeGroup.author ? 'border-amber-300 focus-visible:ring-amber-400' : ''}
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-slate-400 mb-1 block uppercase tracking-wider">Variant Group</label>
                        <Input
                          value={activeGroup.variant_group_name}
                          onChange={(e) => updateGroup(activeTab, { variant_group_name: e.target.value })}
                          placeholder="Variant group name"
                          disabled={activeGroup.status !== 'pending'}
                        />
                      </div>
                    </div>

                    {/* File toolbar */}
                    {activeGroup.status === 'pending' && (
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
                      />
                    )}

                    {/* File gallery */}
                    <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                      {showSubVariantHeadings ? (
                        subVariantGroups.map((svGroup) => {
                          const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
                          return (
                            <div key={svGroup.subVariant ?? '__main__'} className="mb-1">
                              {/* Sub-variant heading */}
                              <div className="flex items-center gap-2 py-1.5 px-1 sticky top-0 bg-white z-10">
                                {svGroup.subVariant !== null && editingSvHeading === svGroup.subVariant ? (
                                  <input
                                    value={svHeadingDraft}
                                    autoFocus
                                    onChange={(e) => setSvHeadingDraft(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') { renameSubVariant(activeGroup.id, svGroup.subVariant!, svHeadingDraft); setEditingSvHeading(null) }
                                      if (e.key === 'Escape') setEditingSvHeading(null)
                                    }}
                                    onBlur={() => { renameSubVariant(activeGroup.id, svGroup.subVariant!, svHeadingDraft); setEditingSvHeading(null) }}
                                    className="text-[11px] font-semibold text-slate-600 border-b border-emerald-300 bg-transparent outline-none uppercase tracking-wider capitalize"
                                  />
                                ) : (
                                  <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider capitalize whitespace-nowrap">
                                    {svGroup.subVariant ?? 'Main'}
                                  </span>
                                )}
                                {activeGroup.status === 'pending' && svGroup.subVariant !== null && editingSvHeading !== svGroup.subVariant && (
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
                                {activeGroup.status === 'pending' && svGroup.subVariant !== null && editingSvHeading !== svGroup.subVariant && (
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
                                    jobId={jobId!}
                                    vocab={tagVocab}
                                    existingSubVariants={groupSubVariants}
                                    selected={activeSelection.has(file.relative_path)}
                                    onToggleSelect={() => toggleFileSelection(activeGroup.id, file.relative_path)}
                                    onUpdate={(updates) => updateFile(activeTab, file.relative_path, updates)}
                                    disabled={activeGroup.status !== 'pending'}
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
                              jobId={jobId!}
                              vocab={tagVocab}
                              existingSubVariants={groupSubVariants}
                              selected={activeSelection.has(file.relative_path)}
                              onToggleSelect={() => toggleFileSelection(activeGroup.id, file.relative_path)}
                              onUpdate={(updates) => updateFile(activeTab, file.relative_path, updates)}
                              disabled={activeGroup.status !== 'pending'}
                            />
                          ))}
                        </div>
                      )}
                      {filteredFiles.length === 0 && (fileFilter.text || fileFilter.active.length > 0) && (
                        <div className="flex flex-col items-center py-12 text-slate-400 gap-2">
                          <Search className="h-8 w-8 text-slate-200" />
                          <p className="text-sm">No files match the current filter</p>
                        </div>
                      )}
                    </div>

                    {/* Status bar */}
                    {activeGroup.status === 'running' && (
                      <div className="flex flex-col gap-2 flex-shrink-0 pt-3 border-t border-slate-100">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 text-sm text-slate-500">
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-emerald-500" />Processing…
                          </div>
                          <span className="text-xs tabular-nums text-slate-400">
                            {activeGroup.processed} / {activeGroup.total}
                          </span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="bg-emerald-500 h-full rounded-full transition-all duration-500 ease-out"
                            style={{ width: `${activeGroup.total > 0 ? Math.round((activeGroup.processed / activeGroup.total) * 100) : 0}%` }}
                          />
                        </div>
                      </div>
                    )}

                    {activeGroup.status === 'completed' && (
                      <div className="flex items-center gap-2 text-sm flex-shrink-0 pt-3 border-t border-slate-100">
                        <Check className="h-4 w-4 text-emerald-500" />
                        <span className="text-emerald-700">{activeGroup.processed} images processed</span>
                        {activeGroup.failed > 0 && <span className="text-red-500">({activeGroup.failed} failed)</span>}
                      </div>
                    )}

                    {activeGroup.status === 'failed' && (
                      <div className="flex items-center gap-2 text-sm text-red-500 flex-shrink-0 pt-3 border-t border-slate-100">
                        <AlertCircle className="h-4 w-4" />Import failed
                      </div>
                    )}

                    {/* Actions */}
                    {activeGroup.status === 'pending' && (
                      <div className="flex items-center justify-between flex-shrink-0 pt-3 border-t border-slate-100">
                        <span className="text-xs text-slate-400">
                          {activeGroup.files.filter((f) => !f.excluded).length} of {activeGroup.files.length} files selected
                        </span>
                        <div className="flex gap-2">
                          {groups.length > 1 && pendingGroups.length > 1 && (
                            <Button variant="outline" size="sm" onClick={handleConfirmAll}
                              disabled={pendingGroups.some((g) => !g.author)}>
                              Import All ({pendingGroups.length} groups)
                            </Button>
                          )}
                          <Button size="sm" onClick={() => handleConfirmGroup(activeTab)}
                            disabled={!activeGroup.author || activeGroup.files.every((f) => f.excluded)}
                            className="bg-emerald-600 hover:bg-emerald-700 text-white">
                            Import Group
                            <span className="ml-1 opacity-70">({activeGroup.files.filter((f) => !f.excluded).length})</span>
                          </Button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Done ────────────────────────────────────────────────── */}
        {state === 'done' && (
          <div className="flex flex-col items-center py-8 gap-4">
            <div className="h-14 w-14 rounded-2xl bg-emerald-50 flex items-center justify-center">
              <Check className="h-7 w-7 text-emerald-600" />
            </div>
            <div className="text-center">
              <p className="text-lg font-semibold text-slate-800">All done</p>
              <p className="text-sm text-slate-500 mt-1">
                {completedCount} group{completedCount !== 1 ? 's' : ''} imported successfully.
              </p>
            </div>
            <Button onClick={handleClose} className="bg-emerald-600 hover:bg-emerald-700 text-white">Close</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
