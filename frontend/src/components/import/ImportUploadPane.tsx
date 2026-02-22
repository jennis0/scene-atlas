import { Upload, Loader2, AlertCircle, AlertTriangle, FolderOpen, ChevronDown } from 'lucide-react'

interface ImportUploadPaneProps {
  uploading: boolean
  uploadError: string | null
  uploadPhase: string | null
  skippedFiles: string[]
  fileInputRef: React.RefObject<HTMLInputElement>
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
}

export function ImportUploadPane({ uploading, uploadError, uploadPhase, skippedFiles, fileInputRef, onFileSelect }: ImportUploadPaneProps) {
  return (
    <div className="px-6 py-5 space-y-5">
      <p className="text-sm text-muted-foreground">
        Select image or video files, a folder, or a .zip archive to import.
      </p>
      <div className="flex gap-3">
        <input ref={fileInputRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.mp4,.webm,.zip"
          onChange={onFileSelect} className="hidden" id="import-files" />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-md border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-50"
        >
          {uploading
            ? <><Loader2 className="h-4 w-4 animate-spin" />{uploadPhase || 'Analysing\u2026'}</>
            : <><Upload className="h-4 w-4" />Select Files</>
          }
        </button>
        <input type="file"
          // @ts-expect-error webkitdirectory is not in HTMLInputElement type
          webkitdirectory="" multiple onChange={onFileSelect} className="hidden" id="import-folder" />
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
      {skippedFiles.length > 0 && (
        <details className="group text-sm rounded-lg border border-yellow-500/40 bg-yellow-500/10 overflow-hidden">
          <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-2 text-yellow-600 dark:text-yellow-400 marker:content-none list-none">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span className="flex-1">
              {skippedFiles.length} file{skippedFiles.length !== 1 ? 's' : ''} skipped — not an image, video, or ZIP
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
