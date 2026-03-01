import { useState } from 'react'
import {
  UploadCloud,
  Loader2,
  AlertCircle,
  AlertTriangle,
  FolderOpen,
  Files,
  ChevronDown,
  Grid3X3,
  Image,
} from 'lucide-react'
import type { UploadProgress } from '@/types'

interface ImportUploadPaneProps {
  uploading: boolean
  uploadError: string | null
  uploadPhase: string | null
  uploadProgress: UploadProgress | null
  skippedFiles: string[]
  fileInputRef: React.RefObject<HTMLInputElement>
  folderInputRef: React.RefObject<HTMLInputElement>
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
  onDrop: (e: React.DragEvent) => void
  defaultImageType: 'battlemap' | 'scene'
  onDefaultImageTypeChange: (type: 'battlemap' | 'scene') => void
}

export function ImportUploadPane({
  uploading,
  uploadError,
  uploadPhase,
  uploadProgress,
  skippedFiles,
  fileInputRef,
  folderInputRef,
  onFileSelect,
  onDrop,
  defaultImageType,
  onDefaultImageTypeChange,
}: ImportUploadPaneProps) {
  const [isDragOver, setIsDragOver] = useState(false)

  const isUploadingFiles = uploading && uploadProgress?.phase === 'uploading'

  return (
    <div className="px-6 py-5 space-y-4">
      {/* Image type selector */}
      <div className="space-y-1.5">
        <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold block">
          Import as
        </label>
        <div className="inline-flex rounded-lg border border-border p-0.5 bg-secondary/50">
          <button
            onClick={() => onDefaultImageTypeChange('battlemap')}
            disabled={uploading}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-all ${
              defaultImageType === 'battlemap'
                ? 'bg-primary/20 text-primary border border-primary/30 shadow-sm'
                : 'text-muted-foreground hover:text-foreground border border-transparent'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <Grid3X3 className="h-3.5 w-3.5" />
            Battlemap
          </button>
          <button
            onClick={() => onDefaultImageTypeChange('scene')}
            disabled={uploading}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-all ${
              defaultImageType === 'scene'
                ? 'bg-primary/20 text-primary border border-primary/30 shadow-sm'
                : 'text-muted-foreground hover:text-foreground border border-transparent'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <Image className="h-3.5 w-3.5" />
            Scene
          </button>
        </div>
        <p className="text-xs text-muted-foreground/50">
          {defaultImageType === 'battlemap'
            ? 'Grid detection enabled. Optimized for battlemaps and tiles.'
            : 'Grid detection skipped. For vistas, portraits, and encounter art.'}
        </p>
      </div>

      {/* Hidden file inputs */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".jpg,.jpeg,.png,.webp,.mp4,.webm,.zip"
        onChange={onFileSelect}
        className="hidden"
      />
      <input
        ref={folderInputRef}
        type="file"
        // @ts-expect-error webkitdirectory is not in HTMLInputElement type
        webkitdirectory=""
        multiple
        onChange={onFileSelect}
        className="hidden"
      />

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!uploading) setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          setIsDragOver(false)
          onDrop(e)
        }}
        onClick={() => !uploading && fileInputRef.current?.click()}
        className={`
          relative flex flex-col items-center justify-center gap-3
          rounded-xl border-2 border-dashed px-6 py-10
          transition-all duration-150 select-none
          ${
            uploading
              ? 'border-border/40 bg-secondary/20 cursor-default'
              : isDragOver
                ? 'border-primary bg-primary/8 cursor-copy scale-[1.005]'
                : 'border-border/60 hover:border-primary/50 hover:bg-secondary/40 cursor-pointer'
          }
        `}
      >
        {uploading ? (
          isUploadingFiles && uploadProgress ? (
            <UploadProgressDisplay progress={uploadProgress} />
          ) : (
            <>
              <Loader2 className="h-9 w-9 animate-spin text-primary/60" />
              <p className="text-sm font-medium text-muted-foreground">
                {uploadPhase || 'Analysing\u2026'}
              </p>
            </>
          )
        ) : (
          <>
            <UploadCloud
              className={`h-10 w-10 transition-colors ${
                isDragOver ? 'text-primary' : 'text-muted-foreground/40'
              }`}
            />
            <div className="text-center space-y-0.5">
              <p
                className={`text-sm font-medium transition-colors ${isDragOver ? 'text-primary' : 'text-foreground'}`}
              >
                {isDragOver ? 'Drop to import' : 'Drop files or folders here'}
              </p>
              <p className="text-xs text-muted-foreground/60">
                Images, videos, and .zip archives — any mix
              </p>
            </div>

            {/* Secondary browse buttons */}
            <div className="flex items-center gap-2 mt-1" onClick={(e) => e.stopPropagation()}>
              <span className="text-xs text-muted-foreground/40">or</span>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-border/60 bg-secondary/60 text-muted-foreground hover:text-foreground hover:border-border hover:bg-secondary transition-colors"
              >
                <Files className="h-3.5 w-3.5" />
                Browse files
              </button>
              <button
                onClick={() => folderInputRef.current?.click()}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-border/60 bg-secondary/60 text-muted-foreground hover:text-foreground hover:border-border hover:bg-secondary transition-colors"
              >
                <FolderOpen className="h-3.5 w-3.5" />
                Browse folder
              </button>
            </div>
          </>
        )}
      </div>

      {uploadError && (
        <div className="flex items-center gap-2 text-destructive text-sm bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {uploadError}
        </div>
      )}
      {skippedFiles.length > 0 && (
        <details className="group text-sm rounded-lg border border-yellow-500/40 bg-yellow-500/10 overflow-hidden">
          <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-2 text-yellow-600 dark:text-yellow-400 marker:content-none list-none">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span className="flex-1">
              {skippedFiles.length} file{skippedFiles.length !== 1 ? 's' : ''} skipped — not an
              image, video, or ZIP
            </span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-180" />
          </summary>
          <ul className="max-h-36 overflow-y-auto border-t border-yellow-500/30 px-3 py-2 space-y-0.5">
            {skippedFiles.map((name) => (
              <li key={name} className="truncate text-xs text-yellow-700 dark:text-yellow-300/80">
                {name}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

// ── Upload progress display ────────────────────────────────────────────────────

function UploadProgressDisplay({ progress }: { progress: UploadProgress }) {
  const {
    filesUploaded,
    filesTotal,
    bytesUploaded,
    bytesTotal,
    currentBatch,
    totalBatches,
    startTime,
  } = progress

  const pct = bytesTotal > 0 ? Math.min(100, Math.round((bytesUploaded / bytesTotal) * 100)) : 0
  const eta = estimateTimeRemaining(bytesUploaded, bytesTotal, startTime)

  return (
    <div className="w-full space-y-3 px-2">
      {/* Progress bar */}
      <div className="h-1.5 w-full rounded-full bg-secondary overflow-hidden">
        <div
          className="h-full bg-primary rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Stats line */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {filesUploaded} / {filesTotal} file{filesTotal !== 1 ? 's' : ''}
          {bytesTotal > 0 && (
            <span className="text-muted-foreground/60">
              {' · '}
              {formatBytes(bytesUploaded)} / {formatBytes(bytesTotal)}
            </span>
          )}
        </span>
        <span className="tabular-nums">{pct}%</span>
      </div>

      {/* Batch indicator + ETA */}
      <div className="flex items-center justify-between text-xs text-muted-foreground/60">
        {totalBatches > 1 ? (
          <span>
            Batch {currentBatch} of {totalBatches}
          </span>
        ) : (
          <span>Uploading…</span>
        )}
        {eta !== null && <span>{formatDuration(eta)} remaining</span>}
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

function estimateTimeRemaining(
  bytesUploaded: number,
  bytesTotal: number,
  startTime: number,
): number | null {
  if (bytesUploaded <= 0 || bytesTotal <= 0) return null
  const elapsed = (Date.now() - startTime) / 1000 // seconds
  if (elapsed < 1) return null // not enough data yet
  const rate = bytesUploaded / elapsed // bytes/sec
  const remaining = bytesTotal - bytesUploaded
  return remaining / rate
}
