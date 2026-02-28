import { useState, useRef, useCallback } from 'react'
import { filterByMagicBytes } from '@/lib/mimeCheck'
import { importApi } from '@/lib/api'
import { resolveApiUrl } from '@/lib/apiBase'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { humanizeFilename } from '@/components/import/types'
import { collectFilesFromDataTransfer } from '@/lib/fsEntryTraversal'
import { saveImportJobInit, importPreviewUrl } from '@/lib/importStorage'
import type { ImportUploadResponse, EditableGroupState } from '@/types'
import type { DialogState } from './useImportState'
import { ALL_TAB } from './useFileEditing'

interface UseImportUploadOptions {
  setGroups: React.Dispatch<React.SetStateAction<EditableGroupState[]>>
  setJobId: (id: string) => void
  setState: (state: DialogState) => void
  setActiveTab: React.Dispatch<React.SetStateAction<number>>
}

export interface UseImportUploadReturn {
  fileInputRef: React.RefObject<HTMLInputElement>
  folderInputRef: React.RefObject<HTMLInputElement>
  blobUrlsRef: React.MutableRefObject<string[]>
  uploading: boolean
  uploadError: string | null
  uploadPhase: string | null
  skippedFiles: string[]
  defaultImageType: 'battlemap' | 'scene'
  setDefaultImageType: (type: 'battlemap' | 'scene') => void
  handleFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>
  handleDrop: (e: React.DragEvent) => Promise<void>
  clearUploadError: () => void
}

export function useImportUpload({
  setGroups,
  setJobId,
  setState,
  setActiveTab,
}: UseImportUploadOptions): UseImportUploadReturn {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const blobUrlsRef = useRef<string[]>([])

  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadPhase, setUploadPhase] = useState<string | null>(null)
  const [skippedFiles, setSkippedFiles] = useState<string[]>([])
  const [defaultImageType, setDefaultImageType] = useState<'battlemap' | 'scene'>('battlemap')

  const clearUploadError = () => setUploadError(null)

  // ── Core pipeline — accepts pre-built {file, relativePath} pairs ─────────
  const handleFiles = useCallback(
    async (pairs: Array<{ file: File; relativePath: string }>) => {
      if (pairs.length === 0) return
      setUploading(true)
      setUploadError(null)
      setUploadPhase(null)
      setSkippedFiles([])
      try {
        // ── Phase 0: Magic-byte validation ─────────────────────────
        const { valid: validPairs, skipped: invalidNames } = await filterByMagicBytesForPairs(pairs)
        if (invalidNames.length > 0) setSkippedFiles(invalidNames)
        if (validPairs.length === 0) {
          setUploadError(
            'No valid image or ZIP files found. Only JPEG, PNG, WebP, GIF, and ZIP are accepted.',
          )
          return
        }

        // ── Phase 0.5: Create backend job immediately ───────────
        // This ensures the job_id is persisted to localStorage before the
        // upload starts, so closing the dialog mid-upload doesn't lose it.
        setUploadPhase('Initializing\u2026')
        const { job_id: earlyJobId } = await importApi.init()
        setJobId(earlyJobId)
        saveImportJobInit(earlyJobId, validPairs[0]?.file.name ?? 'Import')

        // Build relative paths, blob URLs, and separate ZIPs from image files
        const imageFiles: File[] = []
        const imageRelPaths: string[] = []
        const zipFiles: File[] = []
        const zipRelPaths: string[] = []
        const blobUrlMap: Record<string, string> = {}
        const fileByPath: Record<string, File> = {}

        for (const { file, relativePath } of validPairs) {
          fileByPath[relativePath] = file
          if (file.name.toLowerCase().endsWith('.zip')) {
            zipFiles.push(file)
            zipRelPaths.push(relativePath)
          } else {
            imageFiles.push(file)
            imageRelPaths.push(relativePath)
            const blobUrl = URL.createObjectURL(file)
            blobUrlMap[relativePath] = blobUrl
            blobUrlsRef.current.push(blobUrl)
          }
        }

        // ── Phase 1: Hash image files client-side ──────────────────
        const duplicateFiles = new Map<string, import('@/types').DuplicateInfo>()
        const hashMap = new Map<string, string>()

        if (imageFiles.length > 0) {
          setUploadPhase(`Validating\u2026 0/${imageFiles.length}`)
          const { hashFiles } = await import('@/lib/hashFile')
          const hashed = await hashFiles(
            imageFiles,
            (_file, i) => imageRelPaths[i],
            (p) => setUploadPhase(`Validating\u2026 ${p.current}/${p.total}`),
          )

          // ── Phase 2: Pre-flight duplicate check ────────────────
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

        // ── Phase 3: Upload only new files + ZIPs ────────────────
        const newFiles: File[] = []
        const newRelPaths: string[] = []
        for (let i = 0; i < imageFiles.length; i++) {
          if (!duplicateFiles.has(imageRelPaths[i])) {
            newFiles.push(imageFiles[i])
            newRelPaths.push(imageRelPaths[i])
          }
        }

        const manifest = Array.from(duplicateFiles.entries()).map(([relPath, dupInfo]) => ({
          relative_path: relPath,
          filename: fileByPath[relPath].name,
          content_hash: hashMap.get(relPath)!,
          duplicate_of: dupInfo,
        }))

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
          defaultImageType,
          earlyJobId,
        )

        // ── Phase 4: Map response to editable groups ──────────────
        setUploadPhase('Analysing\u2026')
        const editableGroups = mapAnalysisToEditable(
          response,
          earlyJobId,
          defaultImageType,
          blobUrlMap,
          hashMap,
        )
        setGroups(editableGroups)
        setActiveTab(editableGroups.length > 1 ? ALL_TAB : 0)
        setState('preview')
      } catch (err) {
        setUploadError(getApiErrorMessage(err, 'Upload failed'))
      } finally {
        setUploading(false)
        setUploadPhase(null)
      }
    },
    // defaultImageType intentionally included — changing it between upload sessions is valid
    [defaultImageType, setGroups, setJobId, setState, setActiveTab],
  )

  // ── File input change handler ─────────────────────────────────────────────
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files
    if (!fileList || fileList.length === 0) return
    const pairs = Array.from(fileList).map((file) => ({
      file,
      relativePath:
        (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
    }))
    // Reset before await so the same path can be re-selected later
    e.target.value = ''
    await handleFiles(pairs)
  }

  // ── Drop handler ──────────────────────────────────────────────────────────
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    if (uploading) return
    const pairs = await collectFilesFromDataTransfer(e.dataTransfer)
    if (pairs.length === 0) return
    await handleFiles(pairs)
  }

  return {
    fileInputRef,
    folderInputRef,
    blobUrlsRef,
    uploading,
    uploadError,
    uploadPhase,
    skippedFiles,
    defaultImageType,
    setDefaultImageType,
    handleFileSelect,
    handleDrop,
    clearUploadError,
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * filterByMagicBytes operates on File[], but our pipeline now uses {file, relativePath} pairs.
 * This wrapper preserves the pair association through the magic-byte filter.
 */
async function filterByMagicBytesForPairs(
  pairs: Array<{ file: File; relativePath: string }>,
): Promise<{ valid: typeof pairs; skipped: string[] }> {
  const { valid, skipped } = await filterByMagicBytes(pairs.map((p) => p.file))
  const validSet = new Set(valid)
  return {
    valid: pairs.filter((p) => validSet.has(p.file)),
    skipped,
  }
}

/**
 * Map an ImportUploadResponse (or analysis endpoint response) to editable groups.
 *
 * Used in two places:
 * 1. After a fresh upload completes (has blobUrls and hashMap from client-side processing)
 * 2. On reconnect after dialog close during upload (no blobUrls — uses server preview URLs)
 */
export function mapAnalysisToEditable(
  response: ImportUploadResponse,
  jobId: string,
  defaultImageType: 'battlemap' | 'scene' = 'battlemap',
  blobUrlMap?: Record<string, string>,
  hashMap?: Map<string, string>,
): EditableGroupState[] {
  return response.groups.map((vg) => ({
    id: crypto.randomUUID(),
    author: vg.author || '',
    group_name: vg.group_name,
    files: vg.files.map((f) => ({
      relative_path: f.relative_path,
      filename: f.filename,
      name: f.name || humanizeFilename(f.filename),
      media_type: f.media_type ?? 'image',
      tags: [...f.detected_tags],
      gridded: f.gridded,
      grid_width: f.grid_width,
      grid_height: f.grid_height,
      grid_type: f.grid_type ?? null,
      subgroup: f.subgroup,
      image_type: (f.image_type as 'battlemap' | 'scene') ?? defaultImageType,
      excluded: false,
      previewUrl: f.duplicate_of
        ? resolveApiUrl(`/api/v1/images/${f.duplicate_of.image_id}/thumbnail`)
        : (blobUrlMap?.[f.relative_path] ?? importPreviewUrl(jobId, f.relative_path)),
      content_hash: f.content_hash ?? hashMap?.get(f.relative_path),
      duplicate_of: f.duplicate_of,
      duplicate_action: f.duplicate_of ? 'skip' : undefined,
    })),
    skip: false,
    status: 'pending',
    processed: 0,
    failed: 0,
    total: vg.files.length,
  }))
}
