interface MetadataFormProps {
  author: string
  groupName: string
  authorPlaceholder?: string
  groupNamePlaceholder?: string
  /** When true, author input is disabled */
  authorDisabled?: boolean
  /** When true, group name input is disabled */
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
}: MetadataFormProps) {
  const labelClass =
    'text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1.5 block font-semibold'
  const inputClass =
    'w-full h-8 px-3 text-sm rounded border bg-secondary text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors'
  const hintClass = 'text-[10px] text-muted-foreground/40 mt-1'

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
          list={suggestionsListId}
          disabled={authorDisabled}
          className={`${inputClass} disabled:opacity-40 disabled:cursor-not-allowed ${
            authorHighlight ? 'border-primary/50' : 'border-border'
          }`}
        />
        {isMassEdit && (
          <p className={hintClass}>
            Applies to all images in {isAllTab ? 'each' : 'this'} group
          </p>
        )}
      </div>
      <div>
        <label className={labelClass}>Group Name</label>
        <input
          value={groupName}
          onChange={(e) => onGroupNameChange(e.target.value)}
          onBlur={onBlur}
          placeholder={groupNamePlaceholder}
          disabled={groupNameDisabled}
          className={`${inputClass} border-border disabled:opacity-40 disabled:cursor-not-allowed`}
        />
        {isMassEdit && (
          <p className={hintClass}>
            Applies to all images in {isAllTab ? 'each' : 'this'} group
          </p>
        )}
      </div>
    </div>
  )
}
