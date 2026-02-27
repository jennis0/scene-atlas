import { useState } from 'react'
import { X, Undo2, Pencil, Plus, Copy } from 'lucide-react'
import type { EditableFileState, TagData } from '@/types'
import { resolveApiUrl } from '@/lib/apiBase'
import { TagPicker } from './TagPicker'
import { GridToggle } from './GridToggle'
import { GridSizeInput } from './GridSizeInput'
import { SubgroupDropdown } from '@/components/SubgroupDropdown'
import type { ParsedTagVocab } from './types'
import { useGetTagColor } from '@/contexts/TagColorContext'
import { Dialog, DialogContent } from '@/components/ui/dialog'

interface FileCardProps {
  file: EditableFileState
  jobId: string
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
  jobId,
  vocab,
  existingSubgroups,
  selected,
  onToggleSelect,
  onUpdate,
  disabled,
  excludeTooltip,
}: FileCardProps) {
  const getTagColor = useGetTagColor()
  const [isEditingName, setIsEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [isSubgroupOpen, setIsSubgroupOpen] = useState(false)

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

  // ── Thumbnail renderer (shared across states) ──
  const renderThumb = (opts?: { dimmed?: boolean; small?: boolean }) => {
    const cls = opts?.small ? 'w-20' : 'w-[140px]'
    const filter = opts?.dimmed ? 'grayscale(0.6)' : undefined
    return (
      <button
        type="button"
        className={`${cls} shrink-0 relative overflow-hidden rounded-l-lg bg-secondary cursor-zoom-in min-h-[80px]`}
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
        {/* Selection checkbox overlay */}
        {!opts?.dimmed && (
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

  // ── Out-of-scope state ──
  if (file.outOfScope) {
    return (
      <div className="group/card flex rounded-lg border border-border/20 bg-card/40 opacity-50 hover:opacity-70 transition-opacity overflow-hidden">
        {renderThumb({ small: true })}
        <div className="flex-1 min-w-0 py-2 px-2.5 flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <span
              className="font-display text-[12px] font-semibold text-foreground/60 truncate block"
              title={file.relative_path}
            >
              {file.name || file.filename}
            </span>
            {file.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {file.tags.slice(0, 6).map((tag, i) => {
                  const color = getTagColor(tag.category)
                  return (
                    <span
                      key={i}
                      className={`inline-flex items-center rounded-full border px-1.5 py-px text-[10px] ${color.bg} ${color.text} ${color.border} opacity-60`}
                    >
                      <span className="capitalize">{tag.value}</span>
                    </span>
                  )
                })}
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
        } ${file.duplicate_action === 'skip' ? 'opacity-40' : ''}`}
        onClick={handleCardClick}
      >
        {/* Thumbnail */}
        {renderThumb()}

        {/* Content */}
        <div className="flex-1 min-w-0 flex flex-col py-[7px] px-[9px]">
          {/* Name row */}
          <div className="flex items-center gap-1 mb-px">
            {isEditingName && !disabled ? (
              <input
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={() => {
                  onUpdate({ name: nameDraft })
                  setIsEditingName(false)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    onUpdate({ name: nameDraft })
                    setIsEditingName(false)
                  }
                  if (e.key === 'Escape') setIsEditingName(false)
                }}
                className="font-display text-[12px] font-semibold text-foreground bg-transparent border-b border-primary/70 focus:outline-none flex-1 min-w-0 pb-px leading-snug"
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
                <span className="font-display text-[12px] font-semibold text-foreground truncate leading-snug">
                  {file.name || file.filename}
                </span>
                {!disabled && (
                  <Pencil className="h-2.5 w-2.5 text-muted-foreground/40 opacity-0 group-hover/name:opacity-100 shrink-0 transition-opacity" />
                )}
              </div>
            )}
            {!disabled && (
              <button
                onClick={() => onUpdate({ excluded: true })}
                className="opacity-0 group-hover/card:opacity-100 w-[18px] h-[18px] rounded flex items-center justify-center hover:bg-destructive/10 hover:text-destructive text-muted-foreground/25 transition-all shrink-0"
                title={excludeTooltip ?? 'Exclude from import'}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          {/* Filename */}
          <div className="font-mono text-[9px] text-muted-foreground/40 truncate leading-relaxed mb-1">
            {file.filename}
          </div>

          {/* Duplicate badge (if applicable) */}
          {file.duplicate_of && (
            <div className="flex items-center gap-2 mb-1">
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-400">
                <Copy className="h-2.5 w-2.5" />
                Dup: <span className="font-medium">{file.duplicate_of.name || 'existing'}</span>
              </span>
              {!disabled && (
                <button
                  data-no-select=""
                  onClick={() =>
                    onUpdate({
                      duplicate_action: file.duplicate_action === 'skip' ? 'import' : 'skip',
                    })
                  }
                  className={`text-[10px] rounded border px-1.5 py-0.5 transition-colors ${
                    file.duplicate_action === 'skip'
                      ? 'border-amber-500/30 text-amber-400/80 hover:bg-amber-500/10'
                      : 'border-primary/40 text-primary bg-primary/10'
                  }`}
                >
                  {file.duplicate_action === 'skip' ? 'Skipping' : 'Import as new'}
                </button>
              )}
            </div>
          )}

          {/* Divider */}
          <div className="h-px bg-gradient-to-r from-border/50 to-transparent my-1" />

          {/* SUB prop-row */}
          <div className="flex items-center gap-1.5 min-h-5">
            <span className="w-8 shrink-0 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50 text-right leading-none">
              Sub
            </span>
            <div className="flex-1 min-w-0 flex items-center gap-1 relative">
              {file.subgroup ? (
                <button
                  data-no-select=""
                  className="flex-1 min-w-0 h-5 px-1.5 text-[10px] bg-secondary border border-border rounded text-foreground/80 capitalize text-left truncate flex items-center gap-1 hover:border-primary/40 transition-colors"
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
                  className="flex-1 min-w-0 h-5 px-1.5 text-[10px] bg-secondary border border-border rounded text-muted-foreground/30 italic text-left truncate hover:border-primary/40 transition-colors"
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
                onCommit={(value) => {
                  onUpdate({ subgroup: value || null })
                  setIsSubgroupOpen(false)
                }}
                onCancel={() => setIsSubgroupOpen(false)}
              />
            </div>
          </div>

          {/* TYPE prop-row */}
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
            </div>
          </div>

          {/* GRID prop-row (maps only) */}
          {file.image_type !== 'scene' && (
            <div className="flex items-center gap-1.5 min-h-5">
              <span className="w-8 shrink-0 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50 text-right leading-none">
                Grid
              </span>
              <div className="flex-1 min-w-0 flex items-center gap-1">
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
              </div>
            </div>
          )}

          {/* Divider */}
          <div className="h-px bg-gradient-to-r from-border/50 to-transparent my-1" />

          {/* Tags */}
          <div className="flex flex-wrap items-center gap-1 mt-auto pt-0.5">
            {file.tags.map((tag: TagData, i: number) => {
              const color = getTagColor(tag.category)
              return (
                <span
                  key={`${tag.category}-${tag.value}-${i}`}
                  className={`inline-flex items-center gap-0.5 rounded-full border px-1.5 py-px text-[10px] ${color.bg} ${color.text} ${color.border}`}
                  title={tag.category}
                >
                  <span className="capitalize">{tag.value}</span>
                  {!disabled && (
                    <button
                      onClick={() => onUpdate({ tags: file.tags.filter((_, j) => j !== i) })}
                      className="ml-0.5 opacity-40 hover:opacity-100 transition-opacity"
                    >
                      <X className="h-2 w-2" />
                    </button>
                  )}
                </span>
              )
            })}
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
