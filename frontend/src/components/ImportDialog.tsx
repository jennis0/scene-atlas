import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
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
  FolderOpen,
  Search,
  Pencil,
} from 'lucide-react'
import { importApi, tagApi, imageApi } from '@/lib/api'
import {
  Dialog,
  DialogContent,
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

const ALL_TAB = -1
const ALL_GROUP_ID = '__all__'

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
  // -1 = "All" virtual tab, ≥0 = group index
  const [activeTab, setActiveTab] = useState<number>(ALL_TAB)
  const [tagVocab, setTagVocab] = useState<ParsedTagVocab[]>([])
  const [selections, setSelections] = useState<Record<string, Set<string>>>({})
  const [fileFilter, setFileFilter] = useState<FileFilter>(EMPTY_FILTER)
  const [authorSuggestions, setAuthorSuggestions] = useState<string[]>([])
  const [editingSvHeading, setEditingSvHeading] = useState<string | null>(null)
  const [svHeadingDraft, setSvHeadingDraft] = useState('')

  useEffect(() => { onActiveChange?.(state === 'processing') }, [state, onActiveChange])
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
        if (status.groups.length > 0 && status.groups.every((gs) => gs.status === 'completed' || gs.status === 'failed')) {
          setState('done')
        }
      } catch { /* ignore transient poll errors */ }
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => clearInterval(interval)
  }, [state, jobId])

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
    setActiveTab(ALL_TAB)
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
      // Start on "All" tab if multiple groups, first group if single
      setActiveTab(editableGroups.length > 1 ? ALL_TAB : 0)
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

  // Used in "All" mode — finds and updates the file in whichever group owns it
  const updateFileAnyGroup = (relativePath: string, updates: Partial<EditableFileState>) => {
    setGroups((prev) =>
      prev.map((g) => ({ ...g, files: g.files.map((f) => (f.relative_path === relativePath ? { ...f, ...updates } : f)) }))
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
      if (prev === ALL_TAB) return ALL_TAB
      if (sourceIndex < prev) return prev - 1
      if (sourceIndex === prev) return Math.min(targetIndex, groups.length - 2)
      return prev
    })
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

  // ── Bulk actions (groupId: null = All mode) ───────────────────────

  const bulkAddTag = (groupId: string | null, tag: TagData) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
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

  const bulkSetGrid = (groupId: string | null, value: boolean | null) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
        return { ...g, files: g.files.map((f) => (!sel.has(f.relative_path) || f.excluded ? f : { ...f, gridded: value })) }
      })
    )
  }

  const bulkSetSubVariant = (groupId: string | null, value: string) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    const normalized = value.trim() || null
    setGroups((prev) =>
      prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
        return { ...g, files: g.files.map((f) => (!sel.has(f.relative_path) || f.excluded ? f : { ...f, sub_variant: normalized })) }
      })
    )
  }

  const bulkExclude = (groupId: string | null) => {
    const selId = groupId ?? ALL_GROUP_ID
    const sel = selections[selId] ?? new Set<string>()
    setGroups((prev) =>
      prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
        return { ...g, files: g.files.map((f) => (!sel.has(f.relative_path) ? f : { ...f, excluded: true })) }
      })
    )
    deselectAll(selId)
  }

  const clearSubVariantLabel = (groupId: string, subVariant: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
        return { ...g, files: g.files.map((f) => (f.sub_variant === subVariant && !f.excluded ? { ...f, sub_variant: null } : f)) }
      })
    )
  }

  const renameSubVariant = (groupId: string, oldVal: string, newVal: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g
        return { ...g, files: g.files.map((f) => (f.sub_variant === oldVal && !f.excluded ? { ...f, sub_variant: newVal.trim() || null } : f)) }
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
      ...groups.map((g, i) => (i === sourceIndex ? { ...g, files: remainingFiles, total: remainingFiles.length } : g)),
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
    const toSubmit: { i: number; author: string; variant_group_name: string; files: ImportConfirmFile[] }[] = []
    groups.forEach((group, i) => {
      if (group.status !== 'pending' || group.skip) return
      const confirmFiles = buildConfirmFiles(group)
      if (confirmFiles.length === 0) { updateGroup(i, { status: 'completed', processed: 0 }); return }
      toSubmit.push({ i, author: group.author, variant_group_name: group.variant_group_name, files: confirmFiles })
    })
    if (toSubmit.length === 0) return
    toSubmit.forEach(({ i }) => updateGroup(i, { status: 'running' }))
    try {
      await importApi.confirmAll(jobId, toSubmit.map(({ author, variant_group_name, files }) => ({ author, variant_group_name, files })))
    } catch {
      toSubmit.forEach(({ i }) => updateGroup(i, { status: 'failed' }))
    }
  }

  // ── Derived values ────────────────────────────────────────────────

  const isAllTab = activeTab === ALL_TAB
  const activeGroup = isAllTab ? null : groups[activeTab] ?? null
  const activeGroupId = isAllTab ? ALL_GROUP_ID : (activeGroup?.id ?? '')

  // In "All" mode, show files from all pending (non-skipped) groups
  const allPendingFiles = useMemo(() =>
    groups.filter((g) => g.status === 'pending' && !g.skip).flatMap((g) => g.files),
    [groups]
  )
  const sourceFiles = isAllTab ? allPendingFiles : (activeGroup?.files ?? [])
  const filteredFiles = useMemo(() => applyFileFilter(sourceFiles, fileFilter), [sourceFiles, fileFilter])
  const activeSelection = selections[activeGroupId] ?? new Set<string>()

  const groupSubVariants = useMemo(() => [...new Set(
    sourceFiles.filter((f) => !f.excluded && f.sub_variant).map((f) => f.sub_variant as string)
  )].sort(), [sourceFiles])

  const distinctSubVariants = useMemo(() => [...new Set(filteredFiles.map((f) => f.sub_variant))].sort((a, b) => {
    if (a === null) return -1
    if (b === null) return 1
    return (a ?? '').localeCompare(b ?? '')
  }), [filteredFiles])

  const showSubVariantHeadings = distinctSubVariants.length > 1
  const subVariantGroups = distinctSubVariants.map((sv) => ({
    subVariant: sv,
    files: filteredFiles.filter((f) => f.sub_variant === sv),
  }))

  const pendingGroups = groups.filter((g) => g.status === 'pending' && !g.skip)
  const completedCount = groups.filter((g) => g.status === 'completed').length
  const totalFiles = groups.reduce((sum, g) => sum + g.files.length, 0)

  // For "All" tab author field: show shared value if all groups agree, else empty
  const allSameAuthor = useMemo(() => {
    if (groups.length === 0) return ''
    const first = groups[0].author
    return groups.every((g) => g.author === first) ? first : ''
  }, [groups])

  // Determines whether the active group's import button should be disabled
  const canImportActive = !isAllTab && activeGroup?.status === 'pending' && !!activeGroup.author && !activeGroup.files.every((f) => f.excluded)
  const canImportAll = pendingGroups.length > 0 && pendingGroups.every((g) => !!g.author)

  // ── Render ────────────────────────────────────────────────────────

  const isWide = state === 'preview' || state === 'processing'

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className={`${isWide ? 'max-w-5xl h-[85vh]' : 'max-w-lg'} overflow-hidden flex flex-col p-0 gap-0`}
      >
        {/* Amber stripe */}
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-xl" />

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 pt-6 pb-3 shrink-0">
          <h2 className="font-display text-lg font-semibold flex items-center gap-2 text-foreground">
            {state === 'upload' && <><Upload className="h-5 w-5 text-primary shrink-0" />Import Battlemaps</>}
            {state === 'preview' && <><FolderOpen className="h-5 w-5 text-primary shrink-0" />Review Import</>}
            {state === 'processing' && <><Loader2 className="h-5 w-5 text-primary animate-spin shrink-0" />Processing…</>}
            {state === 'done' && <><Check className="h-5 w-5 text-primary shrink-0" />Import Complete</>}
          </h2>
          <button
            onClick={handleClose}
            className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {/* Amber rule */}
        <div className="h-px bg-gradient-to-r from-primary/60 via-primary/20 to-transparent mx-6 shrink-0" />

        {/* Author datalist */}
        <datalist id="author-suggestions">
          {authorSuggestions.map((a) => <option key={a} value={a} />)}
        </datalist>

        {/* ── Upload state ── */}
        {state === 'upload' && (
          <div className="px-6 py-5 space-y-5">
            <p className="text-sm text-muted-foreground">
              Select image files, a folder, or a .zip archive to import.
            </p>
            <div className="flex gap-3">
              <input ref={fileInputRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.zip"
                onChange={handleFileSelect} className="hidden" id="import-files" />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-md border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-50"
              >
                {uploading
                  ? <><Loader2 className="h-4 w-4 animate-spin" />Analysing…</>
                  : <><Upload className="h-4 w-4" />Select Files</>
                }
              </button>
              <input type="file"
                // @ts-expect-error webkitdirectory is not in HTMLInputElement type
                webkitdirectory="" multiple onChange={handleFileSelect} className="hidden" id="import-folder" />
              <button
                onClick={() => document.getElementById('import-folder')?.click()}
                disabled={uploading}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-md border border-border bg-secondary text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors disabled:opacity-50"
              >
                <FolderOpen className="h-4 w-4" />Select Folder
              </button>
            </div>
            {uploadError && (
              <div className="flex items-center gap-2 text-destructive text-sm bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
                <AlertCircle className="h-4 w-4 shrink-0" />{uploadError}
              </div>
            )}
          </div>
        )}

        {/* ── Preview / Processing — two-column layout ── */}
        {(state === 'preview' || state === 'processing') && groups.length > 0 && (
          <div className="flex min-h-0 flex-1 overflow-hidden">

            {/* ── Left: groups nav (only when >1 group) ── */}
            {groups.length > 1 && (
              <div className="w-[190px] shrink-0 border-r border-border/30 flex flex-col overflow-hidden bg-muted/20">
                <div className="px-3 py-2.5 border-b border-border/30 shrink-0">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold">
                    {groups.length} groups · {totalFiles} files
                  </span>
                </div>

                {/* Scrollable group list */}
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
                      {groups.reduce((s, g) => s + g.files.filter((f) => !f.excluded).length, 0)}
                    </span>
                  </button>
                  <div className="h-px bg-border/30 mx-3 my-0.5" />

                  {groups.map((g, i) => (
                    <div key={g.id} className="flex items-center group/nav">
                      <button
                        onClick={() => setActiveTab(i)}
                        className={`flex-1 flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 min-w-0 ${
                          activeTab === i
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                        } ${g.skip ? 'opacity-40' : ''}`}
                      >
                        <span className="shrink-0 w-3 flex justify-center">
                          {g.status === 'completed' && <Check className="h-3 w-3" />}
                          {g.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
                          {g.status === 'failed' && <AlertCircle className="h-3 w-3 text-destructive" />}
                          {g.status === 'pending' && !g.skip && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-50 inline-block" />}
                          {g.skip && <SkipForward className="h-3 w-3" />}
                        </span>
                        <span className={`flex-1 text-[12px] truncate ${g.skip ? 'line-through' : ''}`}>
                          {g.variant_group_name}
                        </span>
                        <span className="text-[11px] text-muted-foreground/40 tabular-nums shrink-0">
                          {g.files.filter((f) => !f.excluded).length}
                        </span>
                      </button>
                      {g.status === 'pending' && (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button className="opacity-0 group-hover/nav:opacity-100 p-1.5 text-muted-foreground/40 hover:text-muted-foreground transition-all shrink-0">
                              <MoreHorizontal className="h-3.5 w-3.5" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" side="right">
                            <DropdownMenuItem onClick={() => updateGroup(i, { skip: !g.skip })}>
                              <SkipForward className="h-4 w-4 mr-2" />
                              {g.skip ? 'Unskip Group' : 'Skip Group'}
                            </DropdownMenuItem>
                            {groups.length > 1 && (
                              <>
                                <DropdownMenuSeparator />
                                <DropdownMenuLabel className="text-xs text-muted-foreground">Merge into…</DropdownMenuLabel>
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

                {/* Import All button at bottom of sidebar */}
                {pendingGroups.length > 1 && state === 'preview' && (
                  <div className="p-2.5 border-t border-border/30 shrink-0">
                    <button
                      onClick={handleConfirmAll}
                      disabled={!canImportAll}
                      className="w-full text-[12px] py-1.5 rounded border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Import All ({pendingGroups.length})
                    </button>
                  </div>
                )}
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
                      list="author-suggestions"
                      disabled={!isAllTab && activeGroup?.status !== 'pending'}
                      className={`w-full h-8 px-3 text-sm rounded border bg-secondary text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                        !isAllTab && activeGroup?.author === '' && activeGroup?.status === 'pending'
                          ? 'border-primary/50'
                          : 'border-border'
                      }`}
                    />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1.5 block font-semibold">
                      Group Name
                    </label>
                    <input
                      value={isAllTab ? '' : (activeGroup?.variant_group_name ?? '')}
                      onChange={(e) => !isAllTab && updateGroup(activeTab, { variant_group_name: e.target.value })}
                      placeholder={isAllTab ? '— (varies by group)' : 'Variant group name'}
                      disabled={isAllTab || (activeGroup?.status !== 'pending')}
                      className="w-full h-8 px-3 text-sm rounded border border-border bg-secondary text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    />
                  </div>
                </div>
              </div>

              {/* Skip state placeholder */}
              {!isAllTab && activeGroup?.skip ? (
                <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-3">
                  <SkipForward className="h-10 w-10 text-muted-foreground/20" />
                  <p className="text-sm font-medium">Group skipped</p>
                  <button
                    onClick={() => updateGroup(activeTab, { skip: false })}
                    className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary font-medium transition-colors"
                  >
                    <Undo2 className="h-3.5 w-3.5" />Undo
                  </button>
                </div>
              ) : (
                <>
                  {/* File toolbar */}
                  {(isAllTab || activeGroup?.status === 'pending') && (
                    <div className="px-5">
                      <FileToolbar
                        files={sourceFiles}
                        filteredFiles={filteredFiles}
                        selection={activeSelection}
                        filter={fileFilter}
                        vocab={tagVocab}
                        onFilterChange={setFileFilter}
                        onSelectAll={() => selectAllVisible(activeGroupId, filteredFiles)}
                        onDeselectAll={() => deselectAll(activeGroupId)}
                        onBulkAddTag={(tag) => bulkAddTag(isAllTab ? null : activeGroupId, tag)}
                        onBulkSetGrid={(v) => bulkSetGrid(isAllTab ? null : activeGroupId, v)}
                        onBulkSetSubVariant={(v) => bulkSetSubVariant(isAllTab ? null : activeGroupId, v)}
                        onBulkExclude={() => bulkExclude(isAllTab ? null : activeGroupId)}
                        onMoveToNewGroup={!isAllTab && activeGroup?.id ? () => moveToNewGroup(activeGroup.id) : undefined}
                      />
                    </div>
                  )}

                  {/* File gallery */}
                  <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
                    {showSubVariantHeadings ? (
                      subVariantGroups.map((svGroup) => {
                        const nonExcluded = svGroup.files.filter((f) => !f.excluded).length
                        const groupOwner = !isAllTab ? activeGroup : null
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
                                    if (e.key === 'Enter') { renameSubVariant(activeGroup!.id, svGroup.subVariant!, svHeadingDraft); setEditingSvHeading(null) }
                                    if (e.key === 'Escape') setEditingSvHeading(null)
                                  }}
                                  onBlur={() => { renameSubVariant(activeGroup!.id, svGroup.subVariant!, svHeadingDraft); setEditingSvHeading(null) }}
                                  className="text-[11px] font-semibold text-foreground border-b border-primary/70 bg-transparent outline-none uppercase tracking-wider capitalize"
                                />
                              ) : (
                                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider capitalize whitespace-nowrap">
                                  {svGroup.subVariant ?? 'Main'}
                                </span>
                              )}
                              {groupOwner?.status === 'pending' && svGroup.subVariant !== null && !isEditing && (
                                <button
                                  onClick={() => { setSvHeadingDraft(svGroup.subVariant!); setEditingSvHeading(svGroup.subVariant!) }}
                                  className="text-muted-foreground/40 hover:text-muted-foreground transition-colors"
                                >
                                  <Pencil className="h-3 w-3" />
                                </button>
                              )}
                              <div className="flex-1 h-px bg-border/30" />
                              <span className="text-[11px] text-muted-foreground/40 tabular-nums">{nonExcluded}</span>
                              {groupOwner?.status === 'pending' && svGroup.subVariant !== null && !isEditing && (
                                <button
                                  onClick={() => clearSubVariantLabel(activeGroup!.id, svGroup.subVariant!)}
                                  className="text-muted-foreground/40 hover:text-primary transition-colors"
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
                                  jobId={jobId!}
                                  vocab={tagVocab}
                                  existingSubVariants={groupSubVariants}
                                  selected={activeSelection.has(file.relative_path)}
                                  onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
                                  onUpdate={(updates) =>
                                    isAllTab
                                      ? updateFileAnyGroup(file.relative_path, updates)
                                      : updateFile(activeTab, file.relative_path, updates)
                                  }
                                  disabled={!isAllTab && activeGroup?.status !== 'pending'}
                                />
                              ))}
                            </div>
                          </div>
                        )
                      })
                    ) : (
                      <div className="space-y-1.5">
                        {filteredFiles.map((file) => (
                          <FileCard
                            key={file.relative_path}
                            file={file}
                            jobId={jobId!}
                            vocab={tagVocab}
                            existingSubVariants={groupSubVariants}
                            selected={activeSelection.has(file.relative_path)}
                            onToggleSelect={() => toggleFileSelection(activeGroupId, file.relative_path)}
                            onUpdate={(updates) =>
                              isAllTab
                                ? updateFileAnyGroup(file.relative_path, updates)
                                : updateFile(activeTab, file.relative_path, updates)
                            }
                            disabled={!isAllTab && activeGroup?.status !== 'pending'}
                          />
                        ))}
                      </div>
                    )}
                    {filteredFiles.length === 0 && (fileFilter.text || fileFilter.active.length > 0) && (
                      <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
                        <Search className="h-8 w-8 text-muted-foreground/20" />
                        <p className="text-sm">No files match the current filter</p>
                      </div>
                    )}
                    {filteredFiles.length === 0 && !fileFilter.text && fileFilter.active.length === 0 && isAllTab && (
                      <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
                        <p className="text-sm">All groups are complete or skipped</p>
                      </div>
                    )}
                  </div>

                  {/* Per-group status / footer */}
                  {!isAllTab && activeGroup && (
                    <div className="px-5 py-3 border-t border-border/30 shrink-0">
                      {activeGroup.status === 'running' && (
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />Processing…
                            </div>
                            <span className="text-xs tabular-nums text-muted-foreground">
                              {activeGroup.processed} / {activeGroup.total}
                            </span>
                          </div>
                          <div className="w-full bg-secondary rounded-full h-1 overflow-hidden">
                            <div
                              className="bg-primary/70 h-full rounded-full transition-all duration-500 ease-out"
                              style={{ width: `${activeGroup.total > 0 ? Math.round((activeGroup.processed / activeGroup.total) * 100) : 0}%` }}
                            />
                          </div>
                        </div>
                      )}
                      {activeGroup.status === 'completed' && (
                        <div className="flex items-center gap-2 text-sm">
                          <Check className="h-4 w-4 text-primary" />
                          <span className="text-primary">{activeGroup.processed} images processed</span>
                          {activeGroup.failed > 0 && <span className="text-destructive">({activeGroup.failed} failed)</span>}
                        </div>
                      )}
                      {activeGroup.status === 'failed' && (
                        <div className="flex items-center gap-2 text-sm text-destructive">
                          <AlertCircle className="h-4 w-4" />Import failed
                        </div>
                      )}
                      {activeGroup.status === 'pending' && (
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-muted-foreground">
                            {activeGroup.files.filter((f) => !f.excluded).length} of {activeGroup.files.length} files
                          </span>
                          <button
                            onClick={() => handleConfirmGroup(activeTab)}
                            disabled={!canImportActive}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            Import Group
                            <span className="opacity-60 text-xs">({activeGroup.files.filter((f) => !f.excluded).length})</span>
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {/* All-tab footer */}
                  {isAllTab && state === 'preview' && (
                    <div className="px-5 py-3 border-t border-border/30 shrink-0 flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">
                        {groups.reduce((s, g) => s + g.files.filter((f) => !f.excluded).length, 0)} files across {pendingGroups.length} pending groups
                      </span>
                      <button
                        onClick={handleConfirmAll}
                        disabled={!canImportAll}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        Import All ({pendingGroups.length} groups)
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* ── Done ── */}
        {state === 'done' && (
          <div className="flex flex-col items-center py-10 gap-4 px-6">
            <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center">
              <Check className="h-7 w-7 text-primary" />
            </div>
            <div className="text-center">
              <p className="font-display text-xl font-semibold text-foreground">All done</p>
              <p className="text-sm text-muted-foreground mt-1">
                {completedCount} group{completedCount !== 1 ? 's' : ''} imported successfully.
              </p>
            </div>
            <button
              onClick={handleClose}
              className="px-4 py-2 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
            >
              Close
            </button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
