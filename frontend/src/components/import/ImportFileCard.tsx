import { useState } from 'react'
import { X, Copy } from 'lucide-react'
import type { EditableFileState } from '@/types'
import { resolveApiUrl } from '@/lib/apiBase'
import { importPreviewUrl } from '@/lib/importStorage'
import { FileCardThumbnail } from './shared/FileCardThumbnail'
import { FileCardExcludedState } from './shared/FileCardExcludedState'
import { FileCardLightbox } from './shared/FileCardLightbox'
import { TypeToggleInline } from './shared/TypeToggleInline'
import { SubgroupRow } from './shared/SubgroupRow'

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

  const isVideo = file.media_type === 'video'
  const previewUrl = file.previewUrl ?? resolveApiUrl(importPreviewUrl(jobId, file.relative_path))
  const useVideoThumb = isVideo && !!file.previewUrl?.startsWith('blob:')
  const isSkipped = file.duplicate_action === 'skip'

  const handleCardClick = (e: React.MouseEvent) => {
    if (disabled) return
    const target = e.target as Element
    if (target.closest('button, input, [data-no-select]')) return
    onToggleSelect()
  }

  // ── Excluded state ──
  if (file.excluded) {
    return (
      <FileCardExcludedState
        file={file}
        previewUrl={previewUrl}
        useVideoThumb={useVideoThumb}
        disabled={disabled}
        onRestore={() => onUpdate({ excluded: false })}
        onOpenLightbox={() => setLightboxOpen(true)}
      />
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
          <div className="opacity-35">
            <FileCardThumbnail
              file={file}
              previewUrl={previewUrl}
              useVideoThumb={useVideoThumb}
              selected={selected}
              hideCheckbox
              onOpenLightbox={() => setLightboxOpen(true)}
            />
          </div>
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

        {/* Lightbox — image-only in skipped state */}
        <FileCardLightbox
          open={lightboxOpen}
          onOpenChange={setLightboxOpen}
          src={file.fullImageUrl || previewUrl}
          alt={file.name}
          isVideo={false}
        />
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
        <FileCardThumbnail
          file={file}
          previewUrl={previewUrl}
          useVideoThumb={useVideoThumb}
          selected={selected}
          onOpenLightbox={() => setLightboxOpen(true)}
        />

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
            <SubgroupRow
              subgroup={file.subgroup}
              existingSubgroups={existingSubgroups}
              disabled={disabled}
              onUpdate={(subgroup) => onUpdate({ subgroup })}
            />

            {/* TYPE prop-row — duplicate badge sits here with ml-auto */}
            <div className="flex items-center gap-1.5 min-h-5">
              <span className="w-8 shrink-0 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50 text-right leading-none">
                Type
              </span>
              <div className="flex-1 min-w-0 flex items-center gap-1">
                <TypeToggleInline
                  imageType={file.image_type}
                  disabled={disabled}
                  onUpdate={(imageType) => onUpdate({ image_type: imageType })}
                />

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
      <FileCardLightbox
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        src={file.fullImageUrl || previewUrl}
        alt={file.name}
        isVideo={isVideo}
      />
    </>
  )
}
