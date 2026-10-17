import { useState } from 'react'
import { X, Pencil, Plus } from 'lucide-react'
import type { EditableFileState, TagData } from '@/types'
import { MAX_NAME_LENGTH } from '@/lib/constants'
import { onInlineEditKey } from '@/lib/inlineEditKeys'
import { TagPicker } from './TagPicker'
import { GridToggle } from './GridToggle'
import { GridSizeInput } from './GridSizeInput'
import type { ParsedTagVocab } from './types'
import { TagChip } from '@/components/TagChip'
import { FileCardThumbnail } from './shared/FileCardThumbnail'
import { FileCardExcludedState } from './shared/FileCardExcludedState'
import { FileCardLightbox } from './shared/FileCardLightbox'
import { TypeToggleInline } from './shared/TypeToggleInline'
import { SubgroupRow } from './shared/SubgroupRow'

interface FileCardProps {
  file: EditableFileState
  vocab: ParsedTagVocab[]
  existingSubgroups: string[]
  selected: boolean
  onToggleSelect: () => void
  onUpdate: (updates: Partial<EditableFileState>) => void
  disabled?: boolean
  excludeTooltip?: string
}

export function FileCard({
  file,
  vocab,
  existingSubgroups,
  selected,
  onToggleSelect,
  onUpdate,
  disabled,
  excludeTooltip,
}: FileCardProps) {
  const [isEditingName, setIsEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [lightboxOpen, setLightboxOpen] = useState(false)

  const isVideo = file.media_type === 'video'
  const previewUrl = file.previewUrl ?? ''
  const useVideoThumb = isVideo && !!file.previewUrl?.startsWith('blob:')

  const handleCardClick = (e: React.MouseEvent) => {
    if (disabled) return
    const target = e.target as Element
    if (target.closest('button, input, [data-no-select]')) return
    onToggleSelect()
  }

  // Out-of-scope state
  if (file.outOfScope) {
    return (
      <div className="group/card flex rounded-lg border border-border/20 bg-card/40 opacity-50 hover:opacity-70 transition-opacity overflow-hidden">
        <FileCardThumbnail
          file={file}
          previewUrl={previewUrl}
          useVideoThumb={useVideoThumb}
          selected={false}
          small
          onOpenLightbox={() => setLightboxOpen(true)}
        />
        <div className="flex-1 min-w-0 py-2 px-2.5 flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <span
              className="font-display text-[14px] font-semibold text-muted-foreground truncate block"
              title={file.relative_path}
            >
              {file.name || file.filename}
            </span>
            {file.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {file.tags.slice(0, 6).map((tag, i) => (
                  <TagChip
                    key={i}
                    category={tag.category}
                    value={tag.value}
                    size="sm"
                    className="opacity-60"
                  />
                ))}
              </div>
            )}
          </div>
          {!disabled && (
            <button
              onClick={() => onUpdate({ outOfScope: false })}
              className="text-xs text-muted-foreground hover:text-primary transition-colors shrink-0 flex items-center gap-1"
              title="Include in edit scope"
            >
              <Plus className="h-3 w-3" />
              Include
            </button>
          )}
        </div>
      </div>
    )
  }

  // Excluded state
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

  // Normal state: horizontal card with labeled property rows
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
        <FileCardThumbnail
          file={file}
          previewUrl={previewUrl}
          useVideoThumb={useVideoThumb}
          selected={selected}
          onOpenLightbox={() => setLightboxOpen(true)}
        />

        <div className="flex-1 min-w-0 flex flex-col py-[7px] px-[9px]">
          <div className="flex items-center gap-1 mb-px">
            {isEditingName && !disabled ? (
              <input
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={() => {
                  onUpdate({ name: nameDraft })
                  setIsEditingName(false)
                }}
                onKeyDown={(e) =>
                  onInlineEditKey(e, {
                    onEnter: () => {
                      onUpdate({ name: nameDraft })
                      setIsEditingName(false)
                    },
                    onEscape: () => setIsEditingName(false),
                  })
                }
                maxLength={MAX_NAME_LENGTH}
                className="font-display text-[14px] font-semibold text-foreground bg-transparent border-b border-primary/70 focus:outline-none flex-1 min-w-0 pb-px leading-snug"
                autoFocus
                title={file.relative_path}
              />
            ) : (
              <div
                data-no-select=""
                className="group/name flex items-center gap-1 flex-1 min-w-0 cursor-text"
                onClick={() => {
                  if (!disabled) {
                    setNameDraft(file.name)
                    setIsEditingName(true)
                  }
                }}
                title={file.relative_path}
              >
                <span className="font-display text-[14px] font-semibold text-foreground truncate leading-snug">
                  {file.name || file.filename}
                </span>
                {!disabled && (
                  <Pencil className="h-2.5 w-2.5 text-muted-foreground opacity-0 group-hover/name:opacity-100 shrink-0 transition-opacity" />
                )}
              </div>
            )}
            {!disabled && (
              <button
                onClick={() => onUpdate({ excluded: true })}
                className="opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/card:opacity-100 w-[18px] h-[18px] rounded flex items-center justify-center hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-all shrink-0"
                title={excludeTooltip ?? 'Exclude from import'}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          <div
            className="font-mono text-[9px] text-muted-foreground truncate leading-relaxed mb-1"
            title={file.filename}
          >
            {file.filename}
          </div>

          <div className="flex flex-col gap-1">
            <SubgroupRow
              subgroup={file.subgroup}
              existingSubgroups={existingSubgroups}
              disabled={disabled}
              onUpdate={(subgroup) => onUpdate({ subgroup })}
            />

            <div className="flex items-center gap-1.5 min-h-5">
              <span className="w-9 shrink-0 text-[11px] font-semibold text-muted-foreground text-right leading-none">
                Type
              </span>
              <div className="flex-1 min-w-0 flex items-center gap-1">
                <TypeToggleInline
                  imageType={file.image_type}
                  disabled={disabled}
                  onUpdate={(imageType) => onUpdate({ image_type: imageType })}
                />
              </div>
            </div>

            {/* GRID prop-row (content for maps, dash for scenes) */}
            <div className="flex items-center gap-1.5 min-h-5">
              <span className="w-9 shrink-0 text-[11px] font-semibold text-muted-foreground text-right leading-none">
                Grid
              </span>
              <div className="flex-1 min-w-0 flex items-center gap-1">
                {file.image_type !== 'scene' ? (
                  <>
                    <GridToggle
                      gridded={file.gridded}
                      gridType={file.grid_type ?? null}
                      onChange={(gridded, gridType) => onUpdate({ gridded, grid_type: gridType })}
                      disabled={disabled}
                      compact
                    />
                    {file.gridded === true && (
                      <GridSizeInput
                        width={file.grid_width ?? null}
                        height={file.grid_height ?? null}
                        onChange={(w, h) => onUpdate({ grid_width: w, grid_height: h })}
                        disabled={disabled}
                        compact
                      />
                    )}
                  </>
                ) : (
                  <span className="text-[10px] text-muted-foreground">—</span>
                )}
              </div>
            </div>
          </div>

          <div className="h-px bg-border/50 my-1" />

          <div className="flex flex-wrap items-center gap-1 mt-auto pt-0.5">
            {file.tags.map((tag: TagData, i: number) => (
              <TagChip
                key={`${tag.category}-${tag.value}-${i}`}
                category={tag.category}
                value={tag.value}
                size="sm"
                onRemove={
                  disabled
                    ? undefined
                    : () => onUpdate({ tags: file.tags.filter((_, j) => j !== i) })
                }
              />
            ))}
            {!disabled && vocab.length > 0 && (
              <TagPicker
                vocab={vocab}
                existingTags={file.tags}
                onAdd={(tag) => onUpdate({ tags: [...file.tags, tag] })}
              />
            )}
          </div>
        </div>
      </div>

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
