import { Undo2 } from 'lucide-react'
import type { EditableFileState } from '@/types'
import { FileCardThumbnail } from './FileCardThumbnail'

interface FileCardExcludedStateProps {
  file: EditableFileState
  previewUrl: string
  useVideoThumb: boolean
  disabled?: boolean
  onRestore: () => void
  onOpenLightbox: () => void
}

export function FileCardExcludedState({
  file,
  previewUrl,
  useVideoThumb,
  disabled,
  onRestore,
  onOpenLightbox,
}: FileCardExcludedStateProps) {
  return (
    <div className="flex rounded-lg border border-dashed border-border/40 bg-muted/20 opacity-40 overflow-hidden">
      <FileCardThumbnail
        file={file}
        previewUrl={previewUrl}
        useVideoThumb={useVideoThumb}
        selected={false}
        dimmed
        onOpenLightbox={onOpenLightbox}
      />
      <div className="flex-1 min-w-0 py-2 px-2.5 flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <span
            className="font-display text-[14px] text-muted-foreground line-through truncate block"
            title={file.relative_path}
          >
            {file.name || file.filename}
          </span>
          <span className="font-mono text-[9px] text-muted-foreground truncate block">
            {file.filename}
          </span>
        </div>
        {!disabled && (
          <button
            onClick={onRestore}
            className="text-xs text-muted-foreground hover:text-primary transition-colors shrink-0 flex items-center gap-1"
          >
            <Undo2 className="h-3 w-3" />
            Restore
          </button>
        )}
      </div>
    </div>
  )
}
