import { useState } from 'react'
import { X, Undo2, Pencil } from 'lucide-react'
import type { EditableFileState, TagData } from '@/types'
import { TagPicker } from './TagPicker'
import { GridToggle } from './GridToggle'
import { SubVariantPicker } from './SubVariantPicker'
import type { ParsedTagVocab } from './types'
import { getTagColor } from './tagColors'
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
  const [isEditingName, setIsEditingName] = useState(false)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [isEditingSubVariant, setIsEditingSubVariant] = useState(false)
  const [subVariantDraft, setSubVariantDraft] = useState('')

  const previewUrl = file.previewUrl ?? `/api/v1/imports/${jobId}/preview/${file.relative_path}`

  if (file.excluded) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-dashed border-slate-200 bg-slate-50/50 px-4 py-3">
        <div className="h-12 w-12 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
          <X className="h-4 w-4 text-slate-300" />
        </div>
        <span className="text-sm text-slate-400 line-through flex-1 truncate" title={file.relative_path}>
          {file.name || file.filename}
        </span>
        {!disabled && (
          <button
            onClick={() => onUpdate({ excluded: false })}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600 hover:text-emerald-700 transition-colors"
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
        className={`group flex items-start gap-3 rounded-xl border p-3 transition-all
          ${selected
            ? 'border-emerald-300 bg-emerald-50/30'
            : 'border-slate-200/80 bg-white hover:border-slate-300 hover:shadow-sm'
          }`}
      >
        {/* Checkbox */}
        {!disabled && (
          <div className="flex items-center pt-0.5 flex-shrink-0">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggleSelect}
              className="h-3.5 w-3.5 rounded border-slate-300 cursor-pointer accent-emerald-600"
            />
          </div>
        )}

        {/* Thumbnail — clickable to open lightbox */}
        <div
          className="h-14 w-14 rounded-lg overflow-hidden bg-slate-100 flex-shrink-0 ring-1 ring-black/5 cursor-zoom-in"
          onClick={() => { if (previewUrl) setLightboxOpen(true) }}
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
              placeholder.className = 'text-[10px] text-slate-300 font-medium'
              placeholder.textContent = 'No preview'
              el.parentElement!.appendChild(placeholder)
            }}
          />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 flex flex-col gap-1.5">
          {/* Row 1: Click-to-edit display name + exclude button */}
          <div className="flex items-start justify-between gap-2">
            {isEditingName && !disabled ? (
              <input
                value={file.name}
                onChange={(e) => onUpdate({ name: e.target.value })}
                onBlur={() => setIsEditingName(false)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') setIsEditingName(false) }}
                className="flex-1 min-w-0 px-1 py-0 text-sm font-medium text-slate-800 bg-transparent border-b border-emerald-300 focus:outline-none"
                autoFocus
                title={file.relative_path}
              />
            ) : (
              <div
                className="group/name flex items-center gap-1 flex-1 min-w-0 cursor-text"
                onClick={() => { if (!disabled) setIsEditingName(true) }}
                title={file.relative_path}
              >
                <span className="text-sm font-medium text-slate-800 truncate">
                  {file.name || file.filename}
                </span>
                {!disabled && (
                  <Pencil className="h-3 w-3 text-slate-300 opacity-0 group-hover/name:opacity-100 flex-shrink-0 transition-opacity" />
                )}
              </div>
            )}
            {!disabled && (
              <button
                onClick={() => onUpdate({ excluded: true })}
                className="opacity-0 group-hover:opacity-100 p-1 rounded-md hover:bg-red-50 hover:text-red-500 text-slate-300 transition-all flex-shrink-0"
                title="Exclude from import"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          {/* Row 2: Tags */}
          <div className="flex flex-wrap items-center gap-1">
            {file.tags.map((tag: TagData, i: number) => {
              const color = getTagColor(tag.category)
              return (
                <span
                  key={`${tag.category}-${tag.value}-${i}`}
                  className={`inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${color.bg} ${color.text} ${color.border}`}
                >
                  <span className="capitalize">{tag.value}</span>
                  {!disabled && (
                    <button
                      onClick={() => onUpdate({ tags: file.tags.filter((_, j) => j !== i) })}
                      className="ml-0.5 rounded hover:bg-black/5 p-px transition-colors"
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

          {/* Row 3: Grid toggle + sub-variant */}
          <div className="flex items-center gap-3 flex-wrap">
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
                  className="text-[11px] border-b border-violet-400 bg-transparent outline-none w-28 capitalize"
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
                <span className="group/sv inline-flex items-center gap-0.5 rounded-md border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[11px] font-medium text-violet-700">
                  <span className="capitalize">{file.sub_variant}</span>
                  {!disabled && (
                    <>
                      <button
                        className="ml-0.5 opacity-0 group-hover/sv:opacity-100 rounded hover:bg-black/5 p-px transition-opacity"
                        title="Rename sub-variant"
                        onClick={() => { setSubVariantDraft(file.sub_variant!); setIsEditingSubVariant(true) }}
                      >
                        <Pencil className="h-2.5 w-2.5" />
                      </button>
                      <button
                        onClick={() => onUpdate({ sub_variant: null })}
                        className="ml-0.5 rounded hover:bg-black/5 p-px transition-colors"
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
