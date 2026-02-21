import { useState } from 'react'
import { X, Undo2, Pencil, Plus, Copy } from 'lucide-react'
import type { EditableFileState, TagData } from '@/types'
import { TagPicker } from './TagPicker'
import { GridToggle } from './GridToggle'
import { SubVariantPicker } from './SubVariantPicker'
import type { ParsedTagVocab } from './types'
import { useGetTagColor } from '@/contexts/TagColorContext'
import { Dialog, DialogContent } from '@/components/ui/dialog'

interface FileCardProps {
  file: EditableFileState
  jobId: string
  vocab: ParsedTagVocab[]
  existingSubVariants: string[]
  selected: boolean
  onToggleSelect: () => void
  onUpdate: (updates: Partial<EditableFileState>) => void
  disabled?: boolean
}

export function FileCard({
  file,
  jobId,
  vocab,
  existingSubVariants,
  selected,
  onToggleSelect,
  onUpdate,
  disabled,
}: FileCardProps) {
  const getTagColor = useGetTagColor()
  const [isEditingName, setIsEditingName] = useState(false)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [isEditingSubVariant, setIsEditingSubVariant] = useState(false)
  const [subVariantDraft, setSubVariantDraft] = useState('')

  const previewUrl = file.previewUrl ?? `/api/v1/imports/${jobId}/preview/${file.relative_path}`

  // Allow clicking on non-interactive card areas to toggle selection
  const handleCardClick = (e: React.MouseEvent) => {
    if (disabled) return
    const target = e.target as Element
    if (target.closest('button, input, [data-no-select]')) return
    onToggleSelect()
  }

  if (file.outOfScope) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-border/20 bg-card/40 px-3 py-2.5 opacity-50 hover:opacity-70 transition-opacity">
        <div className="h-20 w-20 rounded overflow-hidden bg-secondary shrink-0 ring-1 ring-border/20 self-center">
          <img
            src={previewUrl}
            alt={file.filename}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        </div>
        <div className="flex-1 min-w-0">
          <span className="font-display text-sm font-semibold text-foreground/60 truncate block" title={file.relative_path}>
            {file.name || file.filename}
          </span>
          {file.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {file.tags.slice(0, 6).map((tag, i) => {
                const color = getTagColor(tag.category)
                return (
                  <span key={i} className={`inline-flex items-center rounded-full border px-1.5 py-px text-[11px] ${color.bg} ${color.text} ${color.border} opacity-60`}>
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
    )
  }

  if (file.excluded) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-dashed border-border/40 bg-muted/20 px-3 py-2.5">
        <div className="h-14 w-14 rounded bg-secondary flex items-center justify-center shrink-0">
          <X className="h-4 w-4 text-muted-foreground/30" />
        </div>
        <div className="flex-1 min-w-0">
          <span className="font-display text-sm text-muted-foreground/40 line-through truncate block" title={file.relative_path}>
            {file.name || file.filename}
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
    )
  }

  return (
    <>
      <div
        className={`group flex items-start gap-3 rounded-lg border p-2.5 transition-all ${
          !disabled ? 'cursor-pointer select-none' : ''
        } ${
          selected
            ? 'border-primary/50 bg-primary/5'
            : 'border-border/40 bg-card hover:border-border/70'
        } ${
          file.duplicate_action === 'skip' ? 'opacity-40' : ''
        }`}
        onClick={handleCardClick}
      >
        {/* Thumbnail — button so closest('button') excludes from selection toggle */}
        <button
          type="button"
          className="h-20 w-20 rounded overflow-hidden bg-secondary shrink-0 ring-1 ring-border/30 cursor-zoom-in self-center"
          onClick={() => { if (previewUrl) setLightboxOpen(true) }}
          tabIndex={-1}
        >
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
              placeholder.className = 'text-[10px] text-muted-foreground/40 font-medium text-center px-1'
              placeholder.textContent = 'No preview'
              el.parentElement!.appendChild(placeholder)
            }}
          />
        </button>

        {/* Content */}
        <div className="flex-1 min-w-0 flex flex-col gap-1.5">
          {/* Name + exclude */}
          <div className="flex items-start justify-between gap-2">
            {isEditingName && !disabled ? (
              <input
                value={file.name}
                onChange={(e) => onUpdate({ name: e.target.value })}
                onBlur={() => setIsEditingName(false)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') setIsEditingName(false) }}
                className="font-display text-sm font-semibold text-foreground bg-transparent border-b border-primary/70 focus:outline-none flex-1 min-w-0 pb-px"
                autoFocus
                title={file.relative_path}
              />
            ) : (
              <div
                data-no-select=""
                className="group/name flex items-center gap-1.5 flex-1 min-w-0 cursor-text"
                onClick={() => { if (!disabled) setIsEditingName(true) }}
                title={file.relative_path}
              >
                <span className="font-display text-sm font-semibold text-foreground truncate leading-snug">
                  {file.name || file.filename}
                </span>
                {!disabled && (
                  <Pencil className="h-3 w-3 text-muted-foreground/40 opacity-0 group-hover/name:opacity-100 shrink-0 transition-opacity" />
                )}
              </div>
            )}
            {!disabled && (
              <button
                onClick={() => onUpdate({ excluded: true })}
                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground/30 transition-all shrink-0 mt-0.5"
                title="Exclude from import"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Duplicate badge */}
          {file.duplicate_of && (
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-400">
                <Copy className="h-3 w-3" />
                Duplicate of <span className="font-medium">{file.duplicate_of.name || 'existing image'}</span>
                {file.duplicate_of.author && (
                  <span className="text-amber-400/60">by {file.duplicate_of.author}</span>
                )}
              </span>
              {!disabled && (
                <button
                  data-no-select=""
                  onClick={() => onUpdate({
                    duplicate_action: file.duplicate_action === 'skip' ? 'import' : 'skip',
                  })}
                  className={`text-[11px] rounded border px-1.5 py-0.5 transition-colors ${
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

          {/* Tags */}
          <div className="flex flex-wrap items-center gap-1">
            {file.tags.map((tag: TagData, i: number) => {
              const color = getTagColor(tag.category)
              return (
                <span
                  key={`${tag.category}-${tag.value}-${i}`}
                  className={`inline-flex items-center gap-0.5 rounded-full border px-1.5 py-px text-[11px] ${color.bg} ${color.text} ${color.border}`}
                  title={tag.category}
                >
                  <span className="capitalize">{tag.value}</span>
                  {!disabled && (
                    <button
                      onClick={() => onUpdate({ tags: file.tags.filter((_, j) => j !== i) })}
                      className="ml-0.5 opacity-40 hover:opacity-100 transition-opacity"
                    >
                      <X className="h-2.5 w-2.5" />
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

          {/* Grid + sub-variant */}
          <div className="flex items-center gap-2.5 flex-wrap">
            <GridToggle
              value={file.gridded}
              onChange={(v) => onUpdate({ gridded: v })}
              disabled={disabled}
            />

            {file.sub_variant ? (
              isEditingSubVariant ? (
                <input
                  value={subVariantDraft}
                  autoFocus
                  className="text-[11px] border-b border-primary/70 bg-transparent outline-none w-28 text-foreground capitalize"
                  onChange={(e) => setSubVariantDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      onUpdate({ sub_variant: subVariantDraft.trim() || null })
                      setIsEditingSubVariant(false)
                    }
                    if (e.key === 'Escape') setIsEditingSubVariant(false)
                  }}
                  onBlur={() => {
                    onUpdate({ sub_variant: subVariantDraft.trim() || null })
                    setIsEditingSubVariant(false)
                  }}
                />
              ) : (
                <span className="group/sv inline-flex items-center gap-0.5 rounded border border-border bg-secondary px-1.5 py-0.5 text-[11px] text-foreground/80">
                  <span className="capitalize">{file.sub_variant}</span>
                  {!disabled && (
                    <>
                      <button
                        className="ml-0.5 opacity-0 group-hover/sv:opacity-60 hover:!opacity-100 transition-opacity"
                        title="Rename sub-variant"
                        onClick={() => { setSubVariantDraft(file.sub_variant!); setIsEditingSubVariant(true) }}
                      >
                        <Pencil className="h-2.5 w-2.5" />
                      </button>
                      <button
                        onClick={() => onUpdate({ sub_variant: null })}
                        className="ml-0.5 opacity-40 hover:opacity-100 transition-opacity"
                        title="Remove sub-variant"
                      >
                        <X className="h-2.5 w-2.5" />
                      </button>
                    </>
                  )}
                </span>
              )
            ) : !disabled ? (
              <SubVariantPicker
                existingSubVariants={existingSubVariants}
                onSelect={(v) => onUpdate({ sub_variant: v || null })}
              />
            ) : null}
          </div>
        </div>
      </div>

      {/* Lightbox */}
      {lightboxOpen && (
        <Dialog open onOpenChange={setLightboxOpen}>
          <DialogContent className="max-w-none max-h-none w-[95vw] h-[95vh] bg-black/95 border-0 p-4 flex items-center justify-center [&>button]:text-white [&>button]:hover:bg-white/20">
            <img
              src={file.fullImageUrl || previewUrl}
              alt={file.name}
              className="max-w-full max-h-full object-contain rounded"
            />
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
