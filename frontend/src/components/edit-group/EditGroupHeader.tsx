import { Pencil, X } from 'lucide-react'

interface EditGroupHeaderProps {
  isMassEdit: boolean
  /** Shown under the title in mass-edit mode once groups have loaded. */
  summary: { images: number; groups: number; ungrouped: number } | null
  onDone: () => void
  saving: boolean
}

const plural = (n: number, word: string) => `${n} ${word}${n !== 1 ? 's' : ''}`

export function EditGroupHeader({ isMassEdit, summary, onDone, saving }: EditGroupHeaderProps) {
  return (
    <>
      <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-xl" />

      <div className="flex items-center justify-between px-6 pt-6 pb-3 shrink-0">
        <div>
          <h2 className="font-display text-lg font-semibold flex items-center gap-2 text-foreground">
            <Pencil className="h-5 w-5 text-primary shrink-0" />
            {isMassEdit ? 'Edit Search Results' : 'Edit Group'}
          </h2>
          {summary && (
            <p className="text-[11px] text-muted-foreground/60 mt-0.5 ml-7">
              {plural(summary.images, 'image')} across {plural(summary.groups, 'group')}
              {summary.ungrouped > 0 && ` · ${summary.ungrouped} ungrouped skipped`}
            </p>
          )}
        </div>
        <button
          onClick={onDone}
          disabled={saving}
          className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-40"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="h-px bg-gradient-to-r from-primary/60 via-primary/20 to-transparent mx-6 shrink-0" />
    </>
  )
}
