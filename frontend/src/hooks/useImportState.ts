import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { filterByMagicBytes } from '@/lib/mimeCheck'
import { importApi, tagApi, imageApi } from '@/lib/api'
import { parseTagVocabulary, humanizeFilename } from '@/components/import/types'
import { EMPTY_FILTER, applyFileFilter } from '@/components/import/fileFilter'
import {
  saveImportState,
  loadImportState,
  restorePreviewUrls,
} from '@/lib/importStorage'
import type { ParsedTagVocab } from '@/components/import/types'
import type { FileFilter } from '@/components/import/fileFilter'
import type {
  ImportUploadResponse,
  EditableFileState,
  EditableGroupState,
  TagData,
  ImportConfirmFile,
} from '@/types'

export type DialogState = 'upload' | 'preview' | 'processing' | 'done'

export const ALL_TAB = -1
export const ALL_GROUP_ID = '__all__'

export interface UseImportStateReturn {
  // Core state
  state: DialogState
  uploading: boolean
  uploadError: string | null
  uploadPhase: string | null
  skippedFiles: string[]
  jobId: string | null
  groups: EditableGroupState[]
  activeTab: number
  tagVocab: ParsedTagVocab[]
  selections: Record<string, Set<string>>
  fileFilter: FileFilter
  authorSuggestions: string[]
  editingSvHeading: string | null
  svHeadingDraft: string

  // Refs
  fileInputRef: React.RefObject<HTMLInputElement>

  // Derived values
  isAllTab: boolean
  activeGroup: EditableGroupState | null
  activeGroupId: string
  allPendingFiles: EditableFileState[]
  sourceFiles: EditableFileState[]
  filteredFiles: EditableFileState[]
  activeSelection: Set<string>
  groupSubVariants: string[]
  distinctSubVariants: (string | null)[]
  showSubVariantHeadings: boolean
  subVariantGroups: { subVariant: string | null; files: EditableFileState[] }[]
  pendingGroups: EditableGroupState[]
  completedCount: number
  totalFiles: number
  allSameAuthor: string
  duplicateCount: number
  skippedDuplicateCount: number
  canImportActive: boolean
  canImportAll: boolean

  // State setters
  setState: (state: DialogState) => void
  setActiveTab: (tab: number) => void
  setFileFilter: (filter: FileFilter) => void
  setEditingSvHeading: (heading: string | null) => void
  setSvHeadingDraft: (draft: string) => void
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>

  // Actions
  reset: () => void
  handleFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>
  updateGroup: (index: number, updates: Partial<EditableGroupState>) => void
  updateFile: (groupIndex: number, relativePath: string, updates: Partial<EditableFileState>) => void
  updateFileAnyGroup: (relativePath: string, updates: Partial<EditableFileState>) => void
  mergeGroups: (sourceIndex: number, targetIndex: number) => void
  toggleFileSelection: (groupId: string, relativePath: string) => void
  selectAllVisible: (groupId: string, visibleFiles: EditableFileState[]) => void
  deselectAll: (groupId: string) => void
  bulkAddTag: (groupId: string | null, tag: TagData) => void
  bulkSetGrid: (groupId: string | null, value: boolean | null) => void
  bulkSetSubVariant: (groupId: string | null, value: string) => void
  bulkExclude: (groupId: string | null) => void
  bulkSetDuplicateAction: (groupId: string | null, action: 'skip' | 'import') => void
  clearSubVariantLabel: (groupId: string, subVariant: string) => void
  renameSubVariant: (groupId: string, oldVal: string, newVal: string) => void
  moveToNewGroup: (sourceGroupId: string) => void
  handleConfirmGroup: (index: number) => Promise<void>
  handleConfirmAll: () => Promise<void>
  buildConfirmFiles: (group: EditableGroupState) => ImportConfirmFile[]
  saveNow: () => void
}

export function useImportState(
  onActiveChange?: (active: boolean) => void,
  reconnectJobId?: string,
): UseImportStateReturn {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const blobUrlsRef = useRef<string[]>([])

  const [state, setState] = useState<DialogState>('upload')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [groups, setGroups] = useState<EditableGroupState[]>([])
  const [activeTab, setActiveTab] = useState<number>(ALL_TAB)
  const [tagVocab, setTagVocab] = useState<ParsedTagVocab[]>([])
  const [selections, setSelections] = useState<Record<string, Set<string>>>({})
  const [fileFilter, setFileFilter] = useState<FileFilter>(EMPTY_FILTER)
  const [authorSuggestions, setAuthorSuggestions] = useState<string[]>([])
  const [editingSvHeading, setEditingSvHeading] = useState<string | null>(null)
  const [svHeadingDraft, setSvHeadingDraft] = useState('')
  const [uploadPhase, setUploadPhase] = useState<string | null>(null)
  const [skippedFiles, setSkippedFiles] = useState<string[]>([])

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

  // ── Persistence: save to localStorage ─────────────────────────────

  const saveNow = useCallback(() => {
    if (!jobId || groups.length === 0) return
    saveImportState(jobId, groups, activeTab, tagVocab)
  }, [jobId, groups, activeTab, tagVocab])

  // Auto-save every 60 seconds while in preview mode
  useEffect(() => {
    if (state !== 'preview' || !jobId) return
    const interval = setInterval(saveNow, 60_000)
    return () => clearInterval(interval)
  }, [state, jobId, saveNow])

  // Save on beforeunload (browser close/navigate)
  useEffect(() => {
    if (!jobId || groups.length === 0) return
    const hasPending = groups.some((g) => g.status === 'pending' && !g.skip)
    if (!hasPending) return
    const handler = () => saveNow()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [jobId, groups, saveNow])

  // ── Persistence: reconnect to existing job ────────────────────────

  useEffect(() => {
    if (!reconnectJobId) return
    const persisted = loadImportState(reconnectJobId)
    if (!persisted) return

    setJobId(reconnectJobId)
    const restoredGroups = restorePreviewUrls(reconnectJobId, persisted.groups)
    setGroups(restoredGroups)
    setActiveTab(persisted.activeTab)
    if (persisted.tagVocab.length > 0) setTagVocab(persisted.tagVocab)

    // Determine dialog state based on group statuses
    const hasRunning = restoredGroups.some((g) => g.status === 'running')
    const hasPending = restoredGroups.some((g) => g.status === 'pending' && !g.skip)
    if (hasRunning) {
      setState('processing')
    } else if (hasPending) {
      setState('preview')
    } else {
      setState('done')
    }

    // Sync with backend for confirmed groups
    importApi.status(reconnectJobId).then((status) => {
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
    }).catch(() => {})
  }, [reconnectJobId]) // eslint-disable-line react-hooks/exhaustive-deps

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
    setSkippedFiles([])
  }, [])

  // ── Upload ────────────────────────────────────────────────────────

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files
    if (!fileList || fileList.length === 0) return
    setUploading(true)
    setUploadError(null)
    setUploadPhase(null)
    setSkippedFiles([])
    try {
      // ── Phase 0: Magic-byte validation ───────────────────────────
      // Reads only the first 12 bytes of every file in parallel — near-instant.
      const { valid: validFiles, skipped: invalidFiles } = await filterByMagicBytes(
        Array.from(fileList),
      )
      if (invalidFiles.length > 0) {
        setSkippedFiles(invalidFiles)
      }
      if (validFiles.length === 0) {
        setUploadError('No valid image or ZIP files found. Only JPEG, PNG, WebP, GIF, and ZIP are accepted.')
        return
      }

      // Build relative paths, blob URLs, and separate ZIPs from image files
      const imageFiles: File[] = []
      const imageRelPaths: string[] = []
      const zipFiles: File[] = []
      const zipRelPaths: string[] = []
      const blobUrlMap: Record<string, string> = {}
      const fileByPath: Record<string, File> = {}

      for (let i = 0; i < validFiles.length; i++) {
        const file = validFiles[i]
        const relPath = (file as any).webkitRelativePath || file.name
        fileByPath[relPath] = file

        if (file.name.toLowerCase().endsWith('.zip')) {
          zipFiles.push(file)
          zipRelPaths.push(relPath)
        } else {
          imageFiles.push(file)
          imageRelPaths.push(relPath)
          const blobUrl = URL.createObjectURL(file)
          blobUrlMap[relPath] = blobUrl
          blobUrlsRef.current.push(blobUrl)
        }
      }

      // ── Phase 1: Hash image files client-side ────────────────────
      // ZIPs are extracted server-side so we can't hash them here
      let duplicateFiles = new Map<string, import('@/types').DuplicateInfo>()
      let hashMap = new Map<string, string>()

      if (imageFiles.length > 0) {
        setUploadPhase(`Validating\u2026 0/${imageFiles.length}`)
        const { hashFiles } = await import('@/lib/hashFile')
        const hashed = await hashFiles(
          imageFiles,
          (_file, i) => imageRelPaths[i],
          (p) => setUploadPhase(`Validating\u2026 ${p.current}/${p.total}`),
        )

        // ── Phase 2: Pre-flight duplicate check ──────────────────
        setUploadPhase('Checking for duplicates\u2026')
        const checkItems = hashed.map((h) => ({
          relative_path: h.relativePath,
          filename: h.file.name,
          content_hash: h.contentHash,
        }))
        const checkResult = await importApi.checkHashes(checkItems)

        for (const r of checkResult.results) {
          hashMap.set(r.relative_path, r.content_hash)
          if (r.duplicate_of) {
            duplicateFiles.set(r.relative_path, r.duplicate_of)
          }
        }
      }

      // ── Phase 3: Upload only new files + ZIPs ──────────────────
      const newFiles: File[] = []
      const newRelPaths: string[] = []
      for (let i = 0; i < imageFiles.length; i++) {
        if (!duplicateFiles.has(imageRelPaths[i])) {
          newFiles.push(imageFiles[i])
          newRelPaths.push(imageRelPaths[i])
        }
      }

      // Build manifest for duplicate files (metadata only, no upload)
      const manifest = Array.from(duplicateFiles.entries()).map(
        ([relPath, dupInfo]) => ({
          relative_path: relPath,
          filename: fileByPath[relPath].name,
          content_hash: hashMap.get(relPath)!,
          duplicate_of: dupInfo,
        }),
      )

      const uploadFiles = [...newFiles, ...zipFiles]
      const uploadRelPaths = [...newRelPaths, ...zipRelPaths]

      const uploadCount = uploadFiles.length
      const skipCount = duplicateFiles.size
      if (uploadCount > 0) {
        setUploadPhase(
          skipCount > 0
            ? `Uploading ${uploadCount} new file${uploadCount !== 1 ? 's' : ''} (${skipCount} duplicate${skipCount !== 1 ? 's' : ''} skipped)\u2026`
            : `Uploading ${uploadCount} file${uploadCount !== 1 ? 's' : ''}\u2026`,
        )
      } else {
        setUploadPhase('Analysing\u2026')
      }

      const response: ImportUploadResponse = await importApi.upload(
        uploadFiles,
        uploadRelPaths,
        manifest.length > 0 ? manifest : undefined,
      )
      setJobId(response.job_id)

      // ── Phase 4: Map response to editable groups ───────────────
      setUploadPhase('Analysing\u2026')
      const editableGroups: EditableGroupState[] = response.variant_groups.map((vg) => ({
        id: crypto.randomUUID(),
        author: vg.author || '',
        variant_group_name: vg.variant_group_name,
        files: vg.files.map((f) => ({
          relative_path: f.relative_path,
          filename: f.filename,
          name: f.name || humanizeFilename(f.filename),
          media_type: f.media_type ?? 'image',
          tags: [...f.detected_tags],
          gridded: f.gridded,
          grid_width: f.grid_width,
          grid_height: f.grid_height,
          sub_variant: f.sub_variant,
          excluded: false,
          // Duplicates not uploaded: use existing image thumbnail for preview
          previewUrl: f.duplicate_of
            ? `/api/v1/images/${f.duplicate_of.image_id}/thumbnail`
            : blobUrlMap[f.relative_path],
          content_hash: f.content_hash ?? hashMap.get(f.relative_path),
          duplicate_of: f.duplicate_of,
          duplicate_action: f.duplicate_of ? 'skip' : undefined,
        })),
        skip: false,
        status: 'pending',
        processed: 0,
        failed: 0,
        total: vg.files.length,
      }))
      setGroups(editableGroups)
      setActiveTab(editableGroups.length > 1 ? ALL_TAB : 0)
      setState('preview')
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || err?.message || 'Upload failed')
    } finally {
      setUploading(false)
      setUploadPhase(null)
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

  // ── Bulk actions ──────────────────────────────────────────────────

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

  const bulkSetDuplicateAction = (groupId: string | null, action: 'skip' | 'import') => {
    setGroups((prev) =>
      prev.map((g) => {
        if (groupId !== null && g.id !== groupId) return g
        return {
          ...g,
          files: g.files.map((f) =>
            f.duplicate_of ? { ...f, duplicate_action: action } : f
          ),
        }
      })
    )
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
      .filter((f) => !f.excluded && f.duplicate_action !== 'skip')
      .map((f) => {
        const base: ImportConfirmFile = {
          relative_path: f.relative_path,
          name: f.name,
          media_type: f.media_type,
          tags: f.tags,
          gridded: f.gridded,
          grid_width: f.grid_width,
          grid_height: f.grid_height,
          sub_variant: f.sub_variant,
        }
        if (f.content_hash) base.content_hash = f.content_hash
        if (f.duplicate_of && f.duplicate_action === 'import') {
          base.reuse_storage_key = f.duplicate_of.storage_key
          base.reuse_thumbnail_key = f.duplicate_of.thumbnail_key ?? undefined
        }
        return base
      })

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
      // Save state after confirm so tray can track this job
      setTimeout(saveNow, 100)
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
      // Save state after confirm so tray can track this job
      setTimeout(saveNow, 100)
    } catch {
      toSubmit.forEach(({ i }) => updateGroup(i, { status: 'failed' }))
    }
  }

  // ── Derived values ────────────────────────────────────────────────

  const isAllTab = activeTab === ALL_TAB
  const activeGroup = isAllTab ? null : groups[activeTab] ?? null
  const activeGroupId = isAllTab ? ALL_GROUP_ID : (activeGroup?.id ?? '')

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
  const duplicateCount = useMemo(() =>
    sourceFiles.filter((f) => !f.excluded && f.duplicate_of).length,
    [sourceFiles]
  )
  const skippedDuplicateCount = useMemo(() =>
    sourceFiles.filter((f) => !f.excluded && f.duplicate_action === 'skip').length,
    [sourceFiles]
  )

  const allSameAuthor = useMemo(() => {
    if (groups.length === 0) return ''
    const first = groups[0].author
    return groups.every((g) => g.author === first) ? first : ''
  }, [groups])

  const canImportActive = !isAllTab && activeGroup?.status === 'pending' && !!activeGroup.author && !activeGroup.files.every((f) => f.excluded)
  const canImportAll = pendingGroups.length > 0 && pendingGroups.every((g) => !!g.author)

  return {
    state, uploading, uploadError, uploadPhase, skippedFiles, jobId, groups, activeTab, tagVocab,
    selections, fileFilter, authorSuggestions, editingSvHeading, svHeadingDraft,
    fileInputRef,
    isAllTab, activeGroup, activeGroupId, allPendingFiles, sourceFiles,
    filteredFiles, activeSelection, groupSubVariants, distinctSubVariants,
    showSubVariantHeadings, subVariantGroups, pendingGroups, completedCount,
    totalFiles, duplicateCount, skippedDuplicateCount,
    allSameAuthor, canImportActive, canImportAll,
    setState, setActiveTab, setFileFilter, setEditingSvHeading,
    setSvHeadingDraft, setGroups,
    reset, handleFileSelect, updateGroup, updateFile, updateFileAnyGroup,
    mergeGroups, toggleFileSelection, selectAllVisible, deselectAll,
    bulkAddTag, bulkSetGrid, bulkSetSubVariant, bulkExclude,
    bulkSetDuplicateAction,
    clearSubVariantLabel, renameSubVariant, moveToNewGroup,
    handleConfirmGroup, handleConfirmAll, buildConfirmFiles,
    saveNow,
  }
}
