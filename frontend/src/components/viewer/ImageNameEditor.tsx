import { useState } from 'react'
import { Pencil } from 'lucide-react'
import { MAX_NAME_LENGTH } from '@/lib/constants'

interface ImageNameEditorProps {
  name: string
  editing: boolean
  onEditingChange: (editing: boolean) => void
  /** Called with a changed, non-empty name; the parent ends editing once it is saved. */
  onRename: (name: string) => void
}

export function ImageNameEditor({
  name,
  editing,
  onEditingChange,
  onRename,
}: ImageNameEditorProps) {
  const [draft, setDraft] = useState(name)

  const startEditing = () => {
    setDraft(name)
    onEditingChange(true)
  }

  const save = () => {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== name) onRename(trimmed)
    else onEditingChange(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') save()
    if (e.key === 'Escape') {
      setDraft(name)
      onEditingChange(false)
    }
  }

  return (
    <div className="group/name flex items-start gap-2 mb-0.5">
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={handleKeyDown}
          maxLength={MAX_NAME_LENGTH}
          className="font-display text-2xl font-semibold bg-transparent border-b border-primary/70 focus:outline-none text-foreground flex-1 min-w-0 pb-px"
        />
      ) : (
        <>
          <h2
            className="font-display text-2xl font-semibold text-foreground cursor-text flex-1 min-w-0 leading-tight"
            onClick={startEditing}
            title="Click to rename"
          >
            {name}
          </h2>
          <button
            onClick={startEditing}
            className="relative target-24 opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/name:opacity-60 hover:!opacity-100 transition-opacity mt-1 text-muted-foreground shrink-0"
            title="Rename"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        </>
      )}
    </div>
  )
}
