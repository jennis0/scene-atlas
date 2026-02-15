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
  Plus,
  ChevronLeft,
  UserRound,
  FolderOpen,
} from 'lucide-react'
import { importApi, tagApi } from '@/lib/api'
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
  ImportJobResponse,
  EditableFileState,
  EditableGroupState,
  TagData,
  TagCategory,
  ImportConfirmFile,
} from '@/types'

type DialogState = 'upload' | 'preview' | 'processing' | 'done'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onActiveChange?: (active: boolean) => void
}

// ── Category colors for tags ────────────────────────────────────────

const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  lighting:    { bg: 'bg-amber-50',    text: 'text-amber-700',    border: 'border-amber-200' },
  weather:     { bg: 'bg-sky-50',      text: 'text-sky-700',      border: 'border-sky-200' },
  season:      { bg: 'bg-orange-50',   text: 'text-orange-700',   border: 'border-orange-200' },
  terrain:     { bg: 'bg-emerald-50',  text: 'text-emerald-700',  border: 'border-emerald-200' },
  biome:       { bg: 'bg-green-50',    text: 'text-green-700',    border: 'border-green-200' },
  environment: { bg: 'bg-teal-50',     text: 'text-teal-700',     border: 'border-teal-200' },
  structure:   { bg: 'bg-stone-50',    text: 'text-stone-700',    border: 'border-stone-200' },
  feature:     { bg: 'bg-violet-50',   text: 'text-violet-700',   border: 'border-violet-200' },
  mood:        { bg: 'bg-rose-50',     text: 'text-rose-700',     border: 'border-rose-200' },
}

const DEFAULT_TAG_COLOR = { bg: 'bg-slate-50', text: 'text-slate-700', border: 'border-slate-200' }

function getTagColor(category: string) {
  return CATEGORY_COLORS[category.toLowerCase()] || DEFAULT_TAG_COLOR
}

// ── Tag Vocabulary Helpers ──────────────────────────────────────────

interface ParsedTagVocab {
  category: string
  values: string[]
}

function parseTagVocabulary(categories: TagCategory[]): ParsedTagVocab[] {
  return categories
    .map((cat) => {
      let values: string[] = []
      if (cat.common_values) {
        try {
          const parsed = JSON.parse(cat.common_values)
          values = parsed.map((entry: string | { value: string }) =>
            typeof entry === 'string' ? entry : entry.value
          )
        } catch { /* skip malformed */ }
      }
      return { category: cat.name, values }
    })
    .filter((v) => v.values.length > 0)
}

// ── Tag Picker ──────────────────────────────────────────────────────

function TagPicker({
  vocab,
  existingTags,
  onAdd,
}: {
  vocab: ParsedTagVocab[]
  existingTags: TagData[]
  onAdd: (tag: TagData) => void
}) {
  const [open, setOpen] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSelectedCategory(null)
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        setSelectedCategory(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [open])

  const existingKeys = new Set(existingTags.map((t) => `${t.category}:${t.value}`))
  const selectedVocab = vocab.find((v) => v.category === selectedCategory)
  const availableValues = selectedVocab
    ? selectedVocab.values.filter((v) => !existingKeys.has(`${selectedCategory}:${v}`))
    : []

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        onClick={() => { setOpen(!open); setSelectedCategory(null) }}
        className="inline-flex items-center gap-1 rounded-full border border-dashed border-emerald-300/60 px-2 py-0.5 text-xs text-emerald-600 hover:border-emerald-400 hover:bg-emerald-50 transition-all"
      >
        <Plus className="h-3 w-3" />
        Tag
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 w-[200px] rounded-xl border bg-white shadow-xl shadow-black/5 overflow-hidden">
          {!selectedCategory ? (
            <div className="py-1">
              <div className="px-3 pt-2 pb-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-widest">
                Pick category
              </div>
              {vocab.map((v) => {
                const color = getTagColor(v.category)
                return (
                  <button
                    key={v.category}
                    onClick={() => setSelectedCategory(v.category)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-slate-50 transition-colors text-left group"
                  >
                    <span className={`w-2 h-2 rounded-full ${color.bg} ${color.border} border`} />
                    <span className="capitalize text-slate-700">{v.category}</span>
                    <span className="ml-auto text-xs text-slate-300 group-hover:text-slate-400">{v.values.length}</span>
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="py-1">
              <button
                onClick={() => setSelectedCategory(null)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors w-full"
              >
                <ChevronLeft className="h-3 w-3" />
                <span className="capitalize">{selectedCategory}</span>
              </button>
              <div className="h-px bg-slate-100 mx-2" />
              <div className="max-h-[200px] overflow-y-auto py-1">
                {availableValues.length === 0 ? (
                  <div className="px-3 py-3 text-xs text-slate-400 italic text-center">
                    All values applied
                  </div>
                ) : (
                  availableValues.map((value) => (
                    <button
                      key={value}
                      onClick={() => {
                        onAdd({
                          category: selectedCategory,
                          value,
                          confidence: 1.0,
                          source: 'manual',
                        })
                        setOpen(false)
                        setSelectedCategory(null)
                      }}
                      className="flex w-full items-center px-3 py-1.5 text-sm text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 transition-colors text-left capitalize"
                    >
                      {value}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Grid Toggle ─────────────────────────────────────────────────────

function GridToggle({
  value,
  onChange,
  disabled,
}: {
  value: boolean | null
  onChange: (v: boolean | null) => void
  disabled?: boolean
}) {
  const options: { label: string; val: boolean | null }[] = [
    { label: 'Grid', val: true },
    { label: 'Gridless', val: false },
    { label: '?', val: null },
  ]

  return (
    <div className="inline-flex rounded-lg overflow-hidden border border-slate-200">
      {options.map((opt, i) => (
        <button
          key={opt.label}
          disabled={disabled}
          onClick={() => onChange(opt.val)}
          className={`px-2 py-0.5 text-[11px] font-medium transition-all disabled:opacity-40
            ${i > 0 ? 'border-l border-slate-200' : ''}
            ${value === opt.val
              ? 'bg-emerald-600 text-white border-emerald-600'
              : 'bg-white text-slate-500 hover:bg-slate-50'
            }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

// ── File Card ───────────────────────────────────────────────────────

function FileCard({
  file,
  jobId,
  vocab,
  onUpdate,
  disabled,
}: {
  file: EditableFileState
  jobId: string
  vocab: ParsedTagVocab[]
  onUpdate: (updates: Partial<EditableFileState>) => void
  disabled?: boolean
}) {
  const previewUrl = `/api/v1/imports/${jobId}/preview/${file.relative_path}`

  if (file.excluded) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-dashed border-slate-200 bg-slate-50/50 px-4 py-3 transition-all">
        <div className="h-14 w-14 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
          <X className="h-5 w-5 text-slate-300" />
        </div>
        <span className="text-sm text-slate-400 line-through flex-1 truncate">
          {file.filename}
        </span>
        {!disabled && (
          <button
            onClick={() => onUpdate({ excluded: false })}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600 hover:text-emerald-700 transition-colors"
          >
            <Undo2 className="h-3 w-3" />
            Restore
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="group flex gap-4 rounded-xl border border-slate-200/80 bg-white p-3 transition-all hover:border-slate-300 hover:shadow-sm">
      {/* Thumbnail */}
      <div className="h-20 w-20 rounded-lg overflow-hidden bg-slate-100 flex-shrink-0 ring-1 ring-black/5">
        <img
          src={previewUrl}
          alt={file.filename}
          loading="lazy"
          className="h-full w-full object-cover"
          onError={(e) => {
            const el = e.target as HTMLImageElement
            el.style.display = 'none'
            el.parentElement!.classList.add('flex', 'items-center', 'justify-center')
            const placeholder = document.createElement('span')
            placeholder.className = 'text-[10px] text-slate-300 font-medium'
            placeholder.textContent = 'No preview'
            el.parentElement!.appendChild(placeholder)
          }}
        />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 flex flex-col gap-1.5">
        {/* Row 1: Filename + remove */}
        <div className="flex items-start justify-between gap-2">
          <span
            className="text-sm font-medium text-slate-800 truncate"
            title={file.relative_path}
          >
            {file.filename}
          </span>
          {!disabled && (
            <button
              onClick={() => onUpdate({ excluded: true })}
              className="opacity-0 group-hover:opacity-100 p-1 rounded-md hover:bg-red-50 hover:text-red-500 text-slate-300 transition-all flex-shrink-0"
              title="Exclude from import"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Row 2: Tags */}
        <div className="flex flex-wrap items-center gap-1">
          {file.tags.map((tag, i) => {
            const color = getTagColor(tag.category)
            return (
              <span
                key={`${tag.category}-${tag.value}-${i}`}
                className={`inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${color.bg} ${color.text} ${color.border} transition-all`}
              >
                <span className="capitalize">{tag.value}</span>
                {!disabled && (
                  <button
                    onClick={() => onUpdate({ tags: file.tags.filter((_, j) => j !== i) })}
                    className="ml-0.5 rounded hover:bg-black/5 p-px transition-colors"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                )}
              </span>
            )
          })}
          {!disabled && vocab.length > 0 && (
            <TagPicker
              vocab={vocab}
              existingTags={file.tags}
              onAdd={(tag) => onUpdate({ tags: [...file.tags, tag] })}
            />
          )}
        </div>

        {/* Row 3: Grid toggle + sub-variant */}
        <div className="flex items-center gap-3">
          <GridToggle
            value={file.gridded}
            onChange={(v) => onUpdate({ gridded: v })}
            disabled={disabled}
          />
          {file.sub_variant && (
            <span className="text-[11px] text-slate-400 truncate">
              {file.sub_variant}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main Dialog ─────────────────────────────────────────────────────

export function ImportDialog({ open, onOpenChange, onActiveChange }: ImportDialogProps) {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [state, setState] = useState<DialogState>('upload')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [groups, setGroups] = useState<EditableGroupState[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [defaultAuthor, setDefaultAuthor] = useState('')
  const [tagVocab, setTagVocab] = useState<ParsedTagVocab[]>([])

  useEffect(() => {
    onActiveChange?.(state === 'processing')
  }, [state, onActiveChange])

  // Fetch tag vocabulary on entering preview
  useEffect(() => {
    if (state === 'preview' && tagVocab.length === 0) {
      tagApi.getCategories().then((cats) => {
        setTagVocab(parseTagVocabulary(cats))
      }).catch(() => {})
    }
  }, [state, tagVocab.length])

  const reset = useCallback(() => {
    setState('upload')
    setUploading(false)
    setUploadError(null)
    setJobId(null)
    setGroups([])
    setActiveTab(0)
    setDefaultAuthor('')
    setTagVocab([])
  }, [])

  const handleClose = useCallback(() => {
    if (state === 'processing') {
      onOpenChange(false)
      return
    }
    if (state === 'done') {
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['search'] })
    }
    reset()
    onOpenChange(false)
  }, [state, queryClient, reset, onOpenChange])

  // ── Upload ──────────────────────────────────────────────────────

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    setUploading(true)
    setUploadError(null)

    try {
      const relativePaths: string[] = []
      for (let i = 0; i < files.length; i++) {
        const relPath = (files[i] as any).webkitRelativePath
        relativePaths.push(relPath || files[i].name)
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
          tags: [...f.detected_tags],
          gridded: f.gridded,
          grid_width: f.grid_width,
          grid_height: f.grid_height,
          sub_variant: f.sub_variant,
          excluded: false,
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

  // ── State helpers ───────────────────────────────────────────────

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

      const merged = prev
        .map((g, i) => {
          if (i === targetIndex) {
            return { ...g, files: [...g.files, ...source.files], total: g.files.length + source.files.length }
          }
          return g
        })
        .filter((_, i) => i !== sourceIndex)

      return merged
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

  // ── Confirm ─────────────────────────────────────────────────────

  const buildConfirmFiles = (group: EditableGroupState): ImportConfirmFile[] => {
    return group.files
      .filter((f) => !f.excluded)
      .map((f) => ({
        relative_path: f.relative_path,
        tags: f.tags,
        gridded: f.gridded,
        grid_width: f.grid_width,
        grid_height: f.grid_height,
        sub_variant: f.sub_variant,
      }))
  }

  const handleConfirmGroup = async (index: number) => {
    if (!jobId) return
    const group = groups[index]
    if (group.skip) return

    const confirmFiles = buildConfirmFiles(group)
    if (confirmFiles.length === 0) return

    updateGroup(index, { status: 'running' })
    setState('processing')

    try {
      const response: ImportJobResponse = await importApi.confirm(jobId, {
        author: group.author,
        variant_group_name: group.variant_group_name,
        files: confirmFiles,
      })
      const gs = response.groups[0]
      updateGroup(index, {
        status: 'completed',
        processed: gs?.processed_files || confirmFiles.length,
        failed: gs?.failed_files || 0,
      })
    } catch {
      updateGroup(index, { status: 'failed' })
    }

    setGroups((prev) => {
      const anyPending = prev.some((g, i) => i !== index && !g.skip && g.status === 'pending')
      if (!anyPending) setState('done')
      else setState('preview')
      return prev
    })
  }

  const handleConfirmAll = async () => {
    if (!jobId) return
    setState('processing')

    for (let i = 0; i < groups.length; i++) {
      const group = groups[i]
      if (group.status !== 'pending' || group.skip) continue

      const confirmFiles = buildConfirmFiles(group)
      if (confirmFiles.length === 0) {
        updateGroup(i, { status: 'completed', processed: 0 })
        continue
      }

      updateGroup(i, { status: 'running' })

      try {
        const response: ImportJobResponse = await importApi.confirm(jobId, {
          author: group.author,
          variant_group_name: group.variant_group_name,
          files: confirmFiles,
        })
        const gs = response.groups[0]
        updateGroup(i, {
          status: 'completed',
          processed: gs?.processed_files || confirmFiles.length,
          failed: gs?.failed_files || 0,
        })
      } catch {
        updateGroup(i, { status: 'failed' })
      }
    }

    setState('done')
  }

  // ── Derived ─────────────────────────────────────────────────────

  const activeGroup = groups[activeTab]
  const pendingGroups = groups.filter((g) => g.status === 'pending' && !g.skip)
  const completedCount = groups.filter((g) => g.status === 'completed').length
  const totalFiles = groups.reduce((sum, g) => sum + g.files.length, 0)
  const hasEmptyAuthors = groups.some((g) => !g.skip && g.author === '' && g.status === 'pending')

  // ── Render ──────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className={`${
          state === 'preview' || state === 'processing' ? 'max-w-5xl' : 'max-w-lg'
        } max-h-[85vh] overflow-hidden flex flex-col`}
        onClose={handleClose}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {state === 'upload' && (
              <>
                <Upload className="h-5 w-5 text-emerald-600" />
                Import Battlemaps
              </>
            )}
            {state === 'preview' && (
              <>
                <FolderOpen className="h-5 w-5 text-emerald-600" />
                Review Import
              </>
            )}
            {state === 'processing' && (
              <>
                <Loader2 className="h-5 w-5 text-emerald-600 animate-spin" />
                Processing...
              </>
            )}
            {state === 'done' && (
              <>
                <Check className="h-5 w-5 text-emerald-600" />
                Import Complete
              </>
            )}
          </DialogTitle>
        </DialogHeader>

        {/* ── Upload ──────────────────────────────────────────── */}
        {state === 'upload' && (
          <div className="space-y-5">
            <p className="text-sm text-muted-foreground">
              Select image files, a folder, or a .zip archive to import.
            </p>

            <div className="flex gap-3">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".jpg,.jpeg,.png,.webp,.zip"
                onChange={handleFileSelect}
                className="hidden"
                id="import-files"
              />
              <Button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                {uploading ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Analysing...
                  </>
                ) : (
                  <>
                    <Upload className="h-4 w-4 mr-2" />
                    Select Files
                  </>
                )}
              </Button>

              <input
                type="file"
                // @ts-expect-error webkitdirectory is not in HTMLInputElement type
                webkitdirectory=""
                multiple
                onChange={handleFileSelect}
                className="hidden"
                id="import-folder"
              />
              <Button
                variant="outline"
                onClick={() => document.getElementById('import-folder')?.click()}
                disabled={uploading}
              >
                <FolderOpen className="h-4 w-4 mr-2" />
                Select Folder
              </Button>
            </div>

            {uploadError && (
              <div className="flex items-center gap-2 text-destructive text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                {uploadError}
              </div>
            )}
          </div>
        )}

        {/* ── Preview / Processing ────────────────────────────── */}
        {(state === 'preview' || state === 'processing') && groups.length > 0 && (
          <div className="flex flex-col gap-3 min-h-0 flex-1">
            {/* Summary */}
            <p className="text-sm text-slate-500 flex-shrink-0">
              {totalFiles} files in {groups.length} group{groups.length !== 1 ? 's' : ''}.
              {' '}Review metadata, then import.
            </p>

            {/* Default author bar */}
            {hasEmptyAuthors && (
              <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-2.5 flex-shrink-0">
                <UserRound className="h-4 w-4 text-amber-500 flex-shrink-0" />
                <span className="text-sm text-amber-700 flex-shrink-0">
                  Missing author
                </span>
                <Input
                  value={defaultAuthor}
                  onChange={(e) => setDefaultAuthor(e.target.value)}
                  placeholder="Enter default author..."
                  className="h-8 text-sm max-w-[200px] bg-white"
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={applyDefaultAuthor}
                  disabled={!defaultAuthor.trim()}
                  className="flex-shrink-0 h-8 text-xs"
                >
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
                      className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-all flex items-center gap-1.5 ${
                        i === activeTab
                          ? 'border-emerald-600 text-emerald-700 font-medium'
                          : 'border-transparent text-slate-400 hover:text-slate-600'
                      } ${g.skip ? 'opacity-40' : ''}`}
                    >
                      {g.status === 'completed' && <Check className="h-3 w-3 text-emerald-500" />}
                      {g.status === 'running' && <Loader2 className="h-3 w-3 animate-spin text-emerald-500" />}
                      {g.status === 'failed' && <AlertCircle className="h-3 w-3 text-red-400" />}
                      {g.skip && <SkipForward className="h-3 w-3" />}
                      <span className={g.skip ? 'line-through' : ''}>
                        {g.variant_group_name}
                      </span>
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
                              <DropdownMenuLabel className="text-xs text-slate-400">Merge into...</DropdownMenuLabel>
                              {groups.map((target, j) =>
                                j !== i ? (
                                  <DropdownMenuItem key={target.id} onClick={() => mergeGroups(i, j)}>
                                    <Merge className="h-4 w-4 mr-2" />
                                    {target.variant_group_name}
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
                    <button
                      onClick={() => updateGroup(activeTab, { skip: false })}
                      className="inline-flex items-center gap-1.5 text-sm text-emerald-600 hover:text-emerald-700 font-medium transition-colors"
                    >
                      <Undo2 className="h-3.5 w-3.5" />
                      Undo
                    </button>
                  </div>
                ) : (
                  <>
                    {/* Group metadata */}
                    <div className="grid grid-cols-2 gap-3 flex-shrink-0">
                      <div>
                        <label className="text-[11px] font-semibold text-slate-400 mb-1 block uppercase tracking-wider">
                          Author
                        </label>
                        <Input
                          value={activeGroup.author}
                          onChange={(e) => updateGroup(activeTab, { author: e.target.value })}
                          placeholder="Author name"
                          disabled={activeGroup.status !== 'pending'}
                          className={!activeGroup.author ? 'border-amber-300 focus-visible:ring-amber-400' : ''}
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-slate-400 mb-1 block uppercase tracking-wider">
                          Variant Group
                        </label>
                        <Input
                          value={activeGroup.variant_group_name}
                          onChange={(e) => updateGroup(activeTab, { variant_group_name: e.target.value })}
                          placeholder="Variant group name"
                          disabled={activeGroup.status !== 'pending'}
                        />
                      </div>
                    </div>

                    {/* File gallery */}
                    <div className="min-h-0 flex-1 overflow-y-auto space-y-2 pr-1">
                      {activeGroup.files.map((file) => (
                        <FileCard
                          key={file.relative_path}
                          file={file}
                          jobId={jobId!}
                          vocab={tagVocab}
                          onUpdate={(updates) => updateFile(activeTab, file.relative_path, updates)}
                          disabled={activeGroup.status !== 'pending'}
                        />
                      ))}
                    </div>

                    {/* Status bar */}
                    {activeGroup.status === 'running' && (
                      <div className="flex items-center gap-2 text-sm text-slate-500 flex-shrink-0 pt-3 border-t border-slate-100">
                        <Loader2 className="h-4 w-4 animate-spin text-emerald-500" />
                        Processing {activeGroup.processed}/{activeGroup.files.filter((f) => !f.excluded).length}...
                      </div>
                    )}

                    {activeGroup.status === 'completed' && (
                      <div className="flex items-center gap-2 text-sm flex-shrink-0 pt-3 border-t border-slate-100">
                        <Check className="h-4 w-4 text-emerald-500" />
                        <span className="text-emerald-700">
                          {activeGroup.processed} images processed
                        </span>
                        {activeGroup.failed > 0 && (
                          <span className="text-red-500">
                            ({activeGroup.failed} failed)
                          </span>
                        )}
                      </div>
                    )}

                    {activeGroup.status === 'failed' && (
                      <div className="flex items-center gap-2 text-sm text-red-500 flex-shrink-0 pt-3 border-t border-slate-100">
                        <AlertCircle className="h-4 w-4" />
                        Import failed
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
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={handleConfirmAll}
                              disabled={pendingGroups.some((g) => !g.author)}
                            >
                              Import All ({pendingGroups.length} groups)
                            </Button>
                          )}
                          <Button
                            size="sm"
                            onClick={() => handleConfirmGroup(activeTab)}
                            disabled={
                              !activeGroup.author ||
                              activeGroup.files.every((f) => f.excluded)
                            }
                            className="bg-emerald-600 hover:bg-emerald-700 text-white"
                          >
                            Import Group
                            <span className="ml-1 opacity-70">
                              ({activeGroup.files.filter((f) => !f.excluded).length})
                            </span>
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

        {/* ── Done ────────────────────────────────────────────── */}
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
            <Button onClick={handleClose} className="bg-emerald-600 hover:bg-emerald-700 text-white">
              Close
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
