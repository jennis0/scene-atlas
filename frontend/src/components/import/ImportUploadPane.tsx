import { Upload, Loader2, AlertCircle, FolderOpen } from 'lucide-react'

interface ImportUploadPaneProps {
  uploading: boolean
  uploadError: string | null
  fileInputRef: React.RefObject<HTMLInputElement>
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
}

export function ImportUploadPane({ uploading, uploadError, fileInputRef, onFileSelect }: ImportUploadPaneProps) {
  return (
    <div className="px-6 py-5 space-y-5">
      <p className="text-sm text-muted-foreground">
        Select image files, a folder, or a .zip archive to import.
      </p>
      <div className="flex gap-3">
        <input ref={fileInputRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.zip"
          onChange={onFileSelect} className="hidden" id="import-files" />
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
    </div>
  )
}
