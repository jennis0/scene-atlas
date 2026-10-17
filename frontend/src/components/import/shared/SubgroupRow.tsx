import { useRef, useState } from 'react'
import { X } from 'lucide-react'
import { SubgroupDropdown } from '@/components/SubgroupDropdown'

interface SubgroupRowProps {
  subgroup: string | null
  existingSubgroups: string[]
  disabled?: boolean
  onUpdate: (subgroup: string | null) => void
}

export function SubgroupRow({ subgroup, existingSubgroups, disabled, onUpdate }: SubgroupRowProps) {
  const [isOpen, setIsOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  return (
    <div className="flex items-center gap-1.5 min-h-5">
      <span className="w-9 shrink-0 text-2xs font-semibold text-muted-foreground text-right leading-none">
        Sub
      </span>
      <div className="flex-1 min-w-0 flex items-center gap-1 relative">
        {subgroup ? (
          <button
            ref={triggerRef}
            data-no-select=""
            className={`flex-1 min-w-0 h-5 px-1.5 text-3xs bg-secondary border border-border text-foreground/80 capitalize text-left truncate flex items-center gap-1 hover:border-primary/40 transition-colors ${isOpen ? 'rounded-t border-b-0' : 'rounded'}`}
            onClick={() => !disabled && setIsOpen(true)}
          >
            <span className="truncate">{subgroup}</span>
            {!disabled && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onUpdate(null)
                }}
                className="ml-auto shrink-0 text-muted-foreground hover:text-foreground opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/card:opacity-100 transition-opacity"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            )}
          </button>
        ) : (
          <button
            ref={triggerRef}
            data-no-select=""
            className={`flex-1 min-w-0 h-5 px-1.5 text-3xs bg-secondary border border-border text-muted-foreground italic text-left truncate hover:border-primary/40 transition-colors ${isOpen ? 'rounded-t border-b-0' : 'rounded'}`}
            onClick={() => !disabled && setIsOpen(true)}
            disabled={disabled}
          >
            —
          </button>
        )}
        <SubgroupDropdown
          isOpen={isOpen}
          existingSubgroups={existingSubgroups}
          initialValue={subgroup ?? ''}
          variant="attached"
          triggerRef={triggerRef}
          onCommit={(value) => {
            onUpdate(value || null)
            setIsOpen(false)
          }}
          onCancel={() => setIsOpen(false)}
        />
      </div>
    </div>
  )
}
