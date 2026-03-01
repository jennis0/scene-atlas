import { useState, useRef, useCallback, useEffect } from 'react'
import { filterByMagicBytes } from '@/lib/mimeCheck'
import { importApi } from '@/lib/api'
import { resolveApiUrl } from '@/lib/apiBase'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { humanizeFilename } from '@/components/import/types'
import { collectFilesFromDataTransfer } from '@/lib/fsEntryTraversal'
import { saveImportJobInit, importPreviewUrl } from '@/lib/importStorage'
import {
  MAX_FILE_SIZE_BYTES,
  MAX_FILE_SIZE_MB,
  MAX_BATCH_FILES,
  MAX_BATCH_BYTES,
  MAX_BATCH_RETRIES,
} from '@/lib/constants'
import type { ImportUploadResponse, EditableGroupState, UploadProgress } from '@/types'
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
  uploadProgress: UploadProgress | null
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

  // Revoke all blob URLs on unmount to prevent memory leaks.
  // Normally reset() handles this, but if the component is unmounted without
  // reset() being called (e.g., parent key change causes remount), this
  // cleanup ensures blob URLs are still freed.
  useEffect(() => {
    return () => {
      // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: blobUrlsRef is stable, cleanup reads current value at unmount time
      blobUrlsRef.current.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [])

  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadPhase, setUploadPhase] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null)
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
      setUploadProgress(null)
      setSkippedFiles([])

      // Track jobId so we can cancel on failure to clean up staging immediately
      let jobIdForCancel: string | null = null

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

        // ── Phase 0.1: File size check ──────────────────────────
        const oversized = validPairs.filter((p) => p.file.size > MAX_FILE_SIZE_BYTES)
        const sizeLimitedPairs = validPairs.filter((p) => p.file.size <= MAX_FILE_SIZE_BYTES)
        if (oversized.length > 0) {
          const oversizedNames = oversized.map(
            (p) => `${p.file.name} (too large, >${MAX_FILE_SIZE_MB}MB)`,
          )
          setSkippedFiles((prev) => [...prev, ...oversizedNames])
        }
        if (sizeLimitedPairs.length === 0) {
          setUploadError(
            `All files exceed the ${MAX_FILE_SIZE_MB}MB size limit. Please use smaller files.`,
          )
          return
        }

        // ── Phase 0.5: Create backend job immediately ───────────
        // This ensures the job_id is persisted to localStorage before the
        // upload starts, so closing the dialog mid-upload doesn't lose it.
        setUploadPhase('Initializing\u2026')
        const { job_id: earlyJobId } = await importApi.init()
        jobIdForCancel = earlyJobId
        setJobId(earlyJobId)
        saveImportJobInit(earlyJobId, sizeLimitedPairs[0]?.file.name ?? 'Import')

        // Build relative paths, blob URLs, and separate ZIPs from image files
        const imageFiles: File[] = []
        const imageRelPaths: string[] = []
        const zipFiles: File[] = []
        const zipRelPaths: string[] = []
        const blobUrlMap: Record<string, string> = {}
        const fileByPath: Record<string, File> = {}

        for (const { file, relativePath } of sizeLimitedPairs) {
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

        // ── Phase 3: Upload only new files + ZIPs in batches ─────
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

        if (uploadFiles.length > 0) {
          const batches = splitIntoBatches(uploadFiles, uploadRelPaths)
          const totalBytesToUpload = uploadFiles.reduce((sum, f) => sum + f.size, 0)
          const skipCount = duplicateFiles.size
          const startTime = Date.now()

          const uploadCount = uploadFiles.length
          setUploadPhase(
            skipCount > 0
              ? `Uploading ${uploadCount} new file${uploadCount !== 1 ? 's' : ''} (${skipCount} duplicate${skipCount !== 1 ? 's' : ''} skipped)\u2026`
              : `Uploading ${uploadCount} file${uploadCount !== 1 ? 's' : ''}\u2026`,
          )

          let bytesUploadedSoFar = 0
          let filesUploadedSoFar = 0

          for (let batchIdx = 0; batchIdx < batches.length; batchIdx++) {
            const batch = batches[batchIdx]
            const batchTotalBytes = batch.files.reduce((s, f) => s + f.size, 0)

            for (let attempt = 0; attempt <= MAX_BATCH_RETRIES; attempt++) {
              try {
                await importApi.uploadBatch(
                  earlyJobId,
                  batch.files,
                  batch.relativePaths,
                  (event) => {
                    const loaded = event.loaded ?? 0
                    setUploadProgress({
                      phase: 'uploading',
                      filesUploaded: filesUploadedSoFar,
                      filesTotal: uploadFiles.length,
                      bytesUploaded: bytesUploadedSoFar + loaded,
                      bytesTotal: totalBytesToUpload,
                      currentBatch: batchIdx + 1,
                      totalBatches: batches.length,
                      currentBatchLoaded: loaded,
                      currentBatchTotal: event.total ?? batchTotalBytes,
                      startTime,
                    })
                  },
                )
                break // success — exit retry loop
              } catch (err) {
                if (isClientError(err) || attempt >= MAX_BATCH_RETRIES) {
                  throw err
                }
                // Exponential backoff: 1s, 2s
                await new Promise((resolve) => setTimeout(resolve, (attempt + 1) * 1000))
              }
            }

            bytesUploadedSoFar += batchTotalBytes
            filesUploadedSoFar += batch.files.length
          }
        }

        // ── Phase 4: Analyse all staged files ─────────────────────
        setUploadPhase('Analysing\u2026')
        setUploadProgress(null)
        const response: ImportUploadResponse = await importApi.analyse(
          earlyJobId,
          manifest.length > 0 ? manifest : undefined,
          defaultImageType,
        )

        // ── Phase 5: Map response to editable groups ──────────────
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
        // Cancel job to clean up staged files immediately on failure
        if (jobIdForCancel) {
          importApi.cancel(jobIdForCancel).catch(() => {
            // Ignore cancel errors — staging TTL will clean up eventually
          })
        }
        setUploadError(getApiErrorMessage(err, 'Upload failed'))
      } finally {
        setUploading(false)
        setUploadPhase(null)
        setUploadProgress(null)
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
    uploadProgress,
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
 * Split files into batches bounded by MAX_BATCH_FILES and MAX_BATCH_BYTES.
 * Uses greedy bin-packing: each batch fills up as many files as possible
 * without exceeding either limit.
 */
export function splitIntoBatches(
  files: File[],
  relativePaths: string[],
): Array<{ files: File[]; relativePaths: string[] }> {
  const batches: Array<{ files: File[]; relativePaths: string[] }> = []
  let batchFiles: File[] = []
  let batchRelPaths: string[] = []
  let batchBytes = 0

  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    const relPath = relativePaths[i]

    // Start a new batch if adding this file would exceed limits (and batch is non-empty)
    if (
      batchFiles.length > 0 &&
      (batchFiles.length >= MAX_BATCH_FILES || batchBytes + file.size > MAX_BATCH_BYTES)
    ) {
      batches.push({ files: batchFiles, relativePaths: batchRelPaths })
      batchFiles = []
      batchRelPaths = []
      batchBytes = 0
    }

    batchFiles.push(file)
    batchRelPaths.push(relPath)
    batchBytes += file.size
  }

  if (batchFiles.length > 0) {
    batches.push({ files: batchFiles, relativePaths: batchRelPaths })
  }

  return batches
}

/**
 * Returns true for 4xx HTTP errors that should not be retried.
 */
export function isClientError(err: unknown): boolean {
  if (err && typeof err === 'object' && 'response' in err) {
    const status = (err as { response?: { status?: number } }).response?.status
    return typeof status === 'number' && status >= 400 && status < 500
  }
  return false
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
    author: vg.author || 'Unknown',
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
