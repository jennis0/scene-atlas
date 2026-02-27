import { useState } from 'react'
import { X, Undo2, Copy } from 'lucide-react'
import type { EditableFileState } from '@/types'
import { resolveApiUrl } from '@/lib/apiBase'
import { SubgroupDropdown } from '@/components/SubgroupDropdown'
import { Dialog, DialogContent } from '@/components/ui/dialog'

interface ImportFileCardProps {
  file: EditableFileState
  jobId: string
  existingSubgroups: string[]
  selected: boolean
  onToggleSelect: () => void
  onUpdate: (updates: Partial<EditableFileState>) => void
  disabled?: boolean
}

export function ImportFileCard({
  file,
  jobId,
  existingSubgroups,
  selected,
  onToggleSelect,
  onUpdate,
  disabled,
}: ImportFileCardProps) {
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [isSubgroupOpen, setIsSubgroupOpen] = useState(false)

  const isVideo = file.media_type === 'video'
  const previewUrl =
    file.previewUrl ?? resolveApiUrl(`/api/v1/imports/${jobId}/preview/${file.relative_path}`)
  const useVideoThumb = isVideo && !!file.previewUrl?.startsWith('blob:')
  const isSkipped = file.duplicate_action === 'skip'

  const handleCardClick = (e: React.MouseEvent) => {
    if (disabled) return
    const target = e.target as Element
    if (target.closest('button, input, [data-no-select]')) return
    onToggleSelect()
  }

  // ── Thumbnail renderer ──
  const renderThumb = (opts?: { dimmed?: boolean }) => {
    const filter = opts?.dimmed ? 'grayscale(0.6)' : undefined
    return (
      <button
        type="button"
        className="w-[140px] shrink-0 relative overflow-hidden rounded-l-lg bg-secondary cursor-zoom-in min-h-[80px]"
        style={{ filter }}
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
            className="absolute inset-0 w-full h-full object-cover pointer-events-none"
          />
        ) : (
          <img
            src={previewUrl}
            alt={file.filename}
            loading="lazy"
            className="absolute inset-0 w-full h-full object-cover pointer-events-none transition-transform duration-300 group-hover/card:scale-[1.04]"
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
        {/* Selection checkbox */}
        {!opts?.dimmed && !isSkipped && (
          <div
            className={`absolute top-1.5 left-1.5 w-4 h-4 rounded-[3px] flex items-center justify-center text-[9px] transition-all backdrop-blur-sm ${
              selected
                ? 'bg-primary/90 border-primary text-primary-foreground font-bold'
                : 'bg-black/35 border-white/20 text-transparent'
            } border-[1.5px]`}
          >
            ✓
          </div>
        )}
      </button>
    )
  }

  // ── Excluded state ──
  if (file.excluded) {
    return (
      <div className="flex rounded-lg border border-dashed border-border/40 bg-muted/20 opacity-40 overflow-hidden">
        {renderThumb({ dimmed: true })}
        <div className="flex-1 min-w-0 py-2 px-2.5 flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <span
              className="font-display text-[12px] text-muted-foreground/40 line-through truncate block"
              title={file.relative_path}
            >
              {file.name || file.filename}
            </span>
            <span className="font-mono text-[9px] text-muted-foreground/25 truncate block">
              {file.filename}
            </span>
          </div>
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
      </div>
    )
  }

  // ── Skipped duplicate state ──
  if (isSkipped) {
    return (
      <>
        <div
          className="group/card flex rounded-lg border border-border/40 bg-card overflow-hidden"
          onClick={handleCardClick}
        >
          <div className="opacity-35">{renderThumb()}</div>
          <div className="flex-1 min-w-0 flex flex-col py-[7px] px-[9px]">
            {/* Name row — "Skipped" badge replaces X button */}
            <div className="flex items-center gap-1 mb-px opacity-35">
              <span
                className="font-display text-[12px] font-semibold text-muted-foreground line-through truncate flex-1 min-w-0 leading-snug"
                title={file.relative_path}
              >
                {file.name || file.filename}
              </span>
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-px text-[9px] text-amber-400 shrink-0 opacity-80">
                <Copy className="h-2.5 w-2.5" />
                Skipped
              </span>
            </div>
            <div className="font-mono text-[9px] text-muted-foreground/25 truncate leading-relaxed opacity-35">
              {file.filename}
            </div>
            {/* Unskip button — full opacity so it's clearly interactable */}
            {!disabled && (
              <button
                data-no-select=""
                onClick={() => onUpdate({ duplicate_action: 'import' })}
                className="mt-1.5 text-[10px] rounded border border-primary/40 text-primary bg-primary/10 hover:bg-primary/20 px-1.5 py-0.5 transition-colors self-start"
              >
                Import as new
              </button>
            )}
          </div>
        </div>

        {/* Lightbox */}
        {lightboxOpen && (
          <Dialog open onOpenChange={setLightboxOpen}>
            <DialogContent
              className="max-w-none max-h-none w-[95vw] h-[95vh] bg-black/95 border-0 p-4 flex items-center justify-center [&>button]:text-white [&>button]:hover:bg-white/20 cursor-pointer"
              onClick={() => setLightboxOpen(false)}
            >
              <img
                src={file.fullImageUrl || previewUrl}
                alt={file.name}
                className="max-w-full max-h-full object-contain rounded cursor-default"
                onClick={(e) => e.stopPropagation()}
              />
            </DialogContent>
          </Dialog>
        )}
      </>
    )
  }

  // ── Normal state: horizontal card with labeled property rows ──
  return (
    <>
      <div
        className={`group/card flex rounded-lg border transition-all ${
          !disabled ? 'cursor-pointer select-none' : ''
        } ${
          selected
            ? 'border-primary/50 bg-card shadow-[0_0_0_1px_rgba(212,168,83,0.2),0_4px_12px_rgba(212,168,83,0.08)]'
            : 'border-border/40 bg-card hover:border-border/70'
        }`}
        onClick={handleCardClick}
      >
        {/* Thumbnail */}
        {renderThumb()}

        {/* Content */}
        <div className="flex-1 min-w-0 flex flex-col py-[7px] px-[9px]">
          {/* Name row */}
          <div className="flex items-center gap-1 mb-px">
            <span
              className="font-display text-[12px] font-semibold text-foreground truncate flex-1 min-w-0 leading-snug"
              title={file.relative_path}
            >
              {file.name || file.filename}
            </span>
            {!disabled && (
              <button
                onClick={() => onUpdate({ excluded: true })}
                className="opacity-0 group-hover/card:opacity-100 w-[18px] h-[18px] rounded flex items-center justify-center hover:bg-destructive/10 hover:text-destructive text-muted-foreground/25 transition-all shrink-0"
                title="Exclude from import"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          {/* Filename */}
          <div className="font-mono text-[9px] text-muted-foreground/40 truncate leading-relaxed mb-1">
            {file.filename}
          </div>

          {/* Property rows */}
          <div className="flex flex-col gap-1">
            {/* SUB prop-row */}
            <div className="flex items-center gap-1.5 min-h-5">
              <span className="w-8 shrink-0 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50 text-right leading-none">
                Sub
              </span>
              <div className="flex-1 min-w-0 flex items-center gap-1 relative">
                {file.subgroup ? (
                  <button
                    data-no-select=""
                    className={`flex-1 min-w-0 h-5 px-1.5 text-[10px] bg-secondary border border-border text-foreground/80 capitalize text-left truncate flex items-center gap-1 hover:border-primary/40 transition-colors ${isSubgroupOpen ? 'rounded-t border-b-0' : 'rounded'}`}
                    onClick={() => !disabled && setIsSubgroupOpen(true)}
                  >
                    <span className="truncate">{file.subgroup}</span>
                    {!disabled && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          onUpdate({ subgroup: null })
                        }}
                        className="ml-auto shrink-0 text-muted-foreground/30 hover:text-foreground opacity-0 group-hover/card:opacity-100 transition-opacity"
                      >
                        <X className="h-2.5 w-2.5" />
                      </button>
                    )}
                  </button>
                ) : (
                  <button
                    data-no-select=""
                    className={`flex-1 min-w-0 h-5 px-1.5 text-[10px] bg-secondary border border-border text-muted-foreground/30 italic text-left truncate hover:border-primary/40 transition-colors ${isSubgroupOpen ? 'rounded-t border-b-0' : 'rounded'}`}
                    onClick={() => !disabled && setIsSubgroupOpen(true)}
                    disabled={disabled}
                  >
                    —
                  </button>
                )}
                <SubgroupDropdown
                  isOpen={isSubgroupOpen}
                  existingSubgroups={existingSubgroups}
                  initialValue={file.subgroup ?? ''}
                  variant="attached"
                  onCommit={(value) => {
                    onUpdate({ subgroup: value || null })
                    setIsSubgroupOpen(false)
                  }}
                  onCancel={() => setIsSubgroupOpen(false)}
                />
              </div>
            </div>

            {/* TYPE prop-row — duplicate badge sits here with ml-auto */}
            <div className="flex items-center gap-1.5 min-h-5">
              <span className="w-8 shrink-0 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50 text-right leading-none">
                Type
              </span>
              <div className="flex-1 min-w-0 flex items-center gap-1">
                {!disabled ? (
                  <div className="inline-flex rounded-md overflow-hidden border border-border">
                    <button
                      onClick={() => onUpdate({ image_type: 'battlemap' })}
                      className={`px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
                        file.image_type !== 'scene'
                          ? 'bg-primary/20 text-primary'
                          : 'text-muted-foreground/50 hover:text-muted-foreground'
                      }`}
                    >
                      Map
                    </button>
                    <button
                      onClick={() => onUpdate({ image_type: 'scene' })}
                      className={`px-1.5 py-0.5 text-[10px] font-medium border-l border-border transition-colors ${
                        file.image_type === 'scene'
                          ? 'bg-primary/20 text-primary'
                          : 'text-muted-foreground/50 hover:text-muted-foreground'
                      }`}
                    >
                      Scene
                    </button>
                  </div>
                ) : (
                  <span className="text-[10px] text-muted-foreground/60 capitalize">
                    {file.image_type === 'scene' ? 'Scene' : 'Map'}
                  </span>
                )}

                {/* Duplicate badge + action on TYPE row */}
                {file.duplicate_of && (
                  <>
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-px text-[10px] text-amber-400 ml-auto shrink-0">
                      <Copy className="h-2.5 w-2.5" />
                      Duplicate
                    </span>
                    {!disabled && (
                      <button
                        data-no-select=""
                        onClick={() =>
                          onUpdate({
                            duplicate_action: file.duplicate_action === 'skip' ? 'import' : 'skip',
                          })
                        }
                        className="text-[10px] rounded border border-amber-500/30 text-amber-400/80 hover:bg-amber-500/10 px-1.5 py-0.5 transition-colors shrink-0"
                      >
                        Skip
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
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
