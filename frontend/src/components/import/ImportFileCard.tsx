import { useState } from 'react'
import { X, Undo2, Copy } from 'lucide-react'
import type { EditableFileState } from '@/types'
import { resolveApiUrl } from '@/lib/apiBase'
import { Dialog, DialogContent } from '@/components/ui/dialog'

interface ImportFileCardProps {
  file: EditableFileState
  jobId: string
  selected: boolean
  onToggleSelect: () => void
  onUpdate: (updates: Partial<EditableFileState>) => void
  disabled?: boolean
}

export function ImportFileCard({
  file,
  jobId,
  selected,
  onToggleSelect,
  onUpdate,
  disabled,
}: ImportFileCardProps) {
  const [lightboxOpen, setLightboxOpen] = useState(false)

  const isVideo = file.media_type === 'video'
  const previewUrl =
    file.previewUrl ?? resolveApiUrl(`/api/v1/imports/${jobId}/preview/${file.relative_path}`)
  const useVideoThumb = isVideo && !!file.previewUrl?.startsWith('blob:')

  const handleCardClick = (e: React.MouseEvent) => {
    if (disabled) return
    const target = e.target as Element
    if (target.closest('button, input, [data-no-select]')) return
    onToggleSelect()
  }

  // ── Excluded state ──────────────────────────────────────────────────────────
  if (file.excluded) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-dashed border-border/40 bg-muted/20 px-3 py-2">
        <div className="h-10 w-10 rounded bg-secondary flex items-center justify-center shrink-0">
          <X className="h-3.5 w-3.5 text-muted-foreground/30" />
        </div>
        <span
          className="font-display text-sm text-muted-foreground/40 line-through truncate flex-1 min-w-0"
          title={file.relative_path}
        >
          {file.name || file.filename}
        </span>
        {!disabled && (
          <button
            onClick={() => onUpdate({ excluded: false })}
            className="text-xs text-muted-foreground hover:text-primary transition-colors shrink-0 flex items-center gap-1"
          >
            <Undo2 className="h-3 w-3" />
            Restore
          </button>
        )}
      </div>
    )
  }

  // ── Normal state ────────────────────────────────────────────────────────────
  return (
    <>
      <div
        className={`group flex items-center gap-3 rounded-lg border px-2.5 py-2 transition-all ${
          !disabled ? 'cursor-pointer select-none' : ''
        } ${
          selected
            ? 'border-primary/50 bg-primary/5'
            : 'border-border/40 bg-card hover:border-border/70'
        } ${file.duplicate_action === 'skip' ? 'opacity-40' : ''}`}
        onClick={handleCardClick}
      >
        {/* Thumbnail */}
        <button
          type="button"
          className="h-14 w-14 rounded overflow-hidden bg-secondary shrink-0 ring-1 ring-border/30 cursor-zoom-in"
          onClick={() => {
            if (previewUrl) setLightboxOpen(true)
          }}
          tabIndex={-1}
        >
          {useVideoThumb ? (
            <video
              src={previewUrl}
              muted
              preload="metadata"
              className="h-full w-full object-cover pointer-events-none"
            />
          ) : (
            <img
              src={previewUrl}
              alt={file.filename}
              loading="lazy"
              className="h-full w-full object-cover pointer-events-none"
              onError={(e) => {
                const el = e.target as HTMLImageElement
                el.style.display = 'none'
                el.parentElement!.classList.add('flex', 'items-center', 'justify-center')
                const placeholder = document.createElement('span')
                placeholder.className =
                  'text-[10px] text-muted-foreground/40 font-medium text-center px-1'
                placeholder.textContent = 'No preview'
                el.parentElement!.appendChild(placeholder)
              }}
            />
          )}
        </button>

        {/* Name + badges */}
        <div className="flex-1 min-w-0 flex flex-col gap-1">
          <span
            className="font-display text-sm font-semibold text-foreground truncate leading-snug"
            title={file.relative_path}
          >
            {file.name || file.filename}
          </span>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Image type toggle */}
            {!disabled && (
              <div className="inline-flex rounded border border-border p-px bg-secondary/50">
                <button
                  onClick={() => onUpdate({ image_type: 'battlemap' })}
                  className={`px-1.5 py-0.5 text-[10px] rounded-sm transition-colors ${
                    file.image_type !== 'scene'
                      ? 'bg-primary/20 text-primary font-medium'
                      : 'text-muted-foreground/60 hover:text-muted-foreground'
                  }`}
                  title="Battlemap — grid detection enabled"
                >
                  Map
                </button>
                <button
                  onClick={() => onUpdate({ image_type: 'scene' })}
                  className={`px-1.5 py-0.5 text-[10px] rounded-sm transition-colors ${
                    file.image_type === 'scene'
                      ? 'bg-primary/20 text-primary font-medium'
                      : 'text-muted-foreground/60 hover:text-muted-foreground'
                  }`}
                  title="Scene — no grid detection"
                >
                  Scene
                </button>
              </div>
            )}
            {disabled && (
              <span className="text-[10px] text-muted-foreground/60">
                {file.image_type === 'scene' ? 'Scene' : 'Map'}
              </span>
            )}

            {/* Subgroup badge (read-only) */}
            {file.subgroup && (
              <span className="inline-flex items-center rounded border border-border bg-secondary px-1.5 py-0.5 text-[11px] text-foreground/80 capitalize">
                {file.subgroup}
              </span>
            )}

            {/* Duplicate badge */}
            {file.duplicate_of && (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-400">
                <Copy className="h-3 w-3" />
                Duplicate
              </span>
            )}
          </div>
        </div>

        {/* Duplicate action toggle */}
        {file.duplicate_of && !disabled && (
          <button
            data-no-select=""
            onClick={() =>
              onUpdate({
                duplicate_action: file.duplicate_action === 'skip' ? 'import' : 'skip',
              })
            }
            className={`text-[11px] rounded border px-1.5 py-0.5 transition-colors shrink-0 ${
              file.duplicate_action === 'skip'
                ? 'border-amber-500/30 text-amber-400/80 hover:bg-amber-500/10'
                : 'border-primary/40 text-primary bg-primary/10'
            }`}
          >
            {file.duplicate_action === 'skip' ? 'Skip' : 'Import'}
          </button>
        )}

        {/* Exclude button */}
        {!disabled && (
          <button
            onClick={() => onUpdate({ excluded: true })}
            className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground/30 transition-all shrink-0"
            title="Exclude from import"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Lightbox */}
      {lightboxOpen && (
        <Dialog open onOpenChange={setLightboxOpen}>
          <DialogContent
            className="max-w-none max-h-none w-[95vw] h-[95vh] bg-black/95 border-0 p-4 flex items-center justify-center [&>button]:text-white [&>button]:hover:bg-white/20 cursor-pointer"
            onClick={() => setLightboxOpen(false)}
          >
            {isVideo ? (
              <video
                src={file.fullImageUrl || previewUrl}
                controls
                autoPlay
                loop
                className="max-w-full max-h-full object-contain rounded cursor-default"
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <img
                src={file.fullImageUrl || previewUrl}
                alt={file.name}
                className="max-w-full max-h-full object-contain rounded cursor-default"
                onClick={(e) => e.stopPropagation()}
              />
            )}
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
