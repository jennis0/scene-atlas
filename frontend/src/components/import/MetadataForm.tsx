import type { Ref } from 'react'
import { MAX_AUTHOR_LENGTH, MAX_NAME_LENGTH } from '@/lib/constants'

interface MetadataFormProps {
  author: string
  groupName: string
  authorPlaceholder?: string
  groupNamePlaceholder?: string
  authorDisabled?: boolean
  groupNameDisabled?: boolean
  /** When true, shows the primary-coloured focus border on the author input */
  authorHighlight?: boolean
  /** When true, renders a hint below each field ("Applies to all images in this group") */
  isMassEdit?: boolean
  /** When true, the hint text reads "each" group instead of "this" group */
  isAllTab?: boolean
  authorSuggestions?: string[]
  /** Unique id for the datalist element — must differ when two forms are on screen at once */
  suggestionsListId?: string
  onAuthorChange: (val: string) => void
  onGroupNameChange: (val: string) => void
  /** Called on blur for either input — used for auto-save */
  onBlur?: () => void
  /** Lets the parent focus the group name input (e.g. after a split). */
  groupNameRef?: Ref<HTMLInputElement>
}

export function MetadataForm({
  author,
  groupName,
  authorPlaceholder = 'Author name',
  groupNamePlaceholder = 'Group name',
  authorDisabled,
  groupNameDisabled,
  authorHighlight,
  isMassEdit,
  isAllTab,
  authorSuggestions,
  suggestionsListId,
  onAuthorChange,
  onGroupNameChange,
  onBlur,
  groupNameRef,
}: MetadataFormProps) {
  const labelClass = 'text-xs text-muted-foreground mb-1.5 block font-semibold'
  const inputClass =
    'w-full h-8 px-3 text-sm rounded border bg-secondary text-foreground placeholder:text-muted-foreground transition-colors'
  const hintClass = 'text-3xs text-muted-foreground mt-1'

  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label className={labelClass}>Author</label>
        {suggestionsListId && authorSuggestions && (
          <datalist id={suggestionsListId}>
            {authorSuggestions.map((a) => (
              <option key={a} value={a} />
            ))}
          </datalist>
        )}
        <input
          value={author}
          onChange={(e) => onAuthorChange(e.target.value)}
          onBlur={onBlur}
          placeholder={authorPlaceholder}
          maxLength={MAX_AUTHOR_LENGTH}
          list={suggestionsListId}
          disabled={authorDisabled}
          className={`${inputClass} disabled:opacity-40 disabled:cursor-not-allowed ${
            authorHighlight ? 'border-primary/50' : 'border-border'
          }`}
        />
        {isMassEdit && (
          <p className={hintClass}>Applies to all images in {isAllTab ? 'each' : 'this'} group</p>
        )}
      </div>
      <div>
        <label className={labelClass}>Group Name</label>
        <input
          ref={groupNameRef}
          value={groupName}
          onChange={(e) => onGroupNameChange(e.target.value)}
          onBlur={onBlur}
          placeholder={groupNamePlaceholder}
          maxLength={MAX_NAME_LENGTH}
          disabled={groupNameDisabled}
          className={`${inputClass} border-border disabled:opacity-40 disabled:cursor-not-allowed`}
        />
        {isMassEdit && (
          <p className={hintClass}>Applies to all images in {isAllTab ? 'each' : 'this'} group</p>
        )}
      </div>
    </div>
  )
}
