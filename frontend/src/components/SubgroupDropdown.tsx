import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { MAX_NAME_LENGTH } from '@/lib/constants'
import { onInlineEditKey } from '@/lib/inlineEditKeys'

interface SubgroupDropdownProps {
  isOpen: boolean
  /** All existing subgroup labels — shown as quick-pick options */
  existingSubgroups: string[]
  /** Pre-filled value for the rename input (current subgroup label) */
  initialValue?: string
  /** Called with the chosen value — either an existing pick or a typed name */
  onCommit: (value: string) => void
  /** Called on Escape or click outside */
  onCancel: () => void
  /**
   * 'attached' — seamless combobox: merges visually with the trigger button above
   *              (flat top, no top border, full width, no gap).
   * 'floating' — standalone dropdown with its own rounding and gap (default).
   */
  variant?: 'attached' | 'floating'
  /** Ref to the trigger element — focus is restored here when the dropdown closes via keyboard */
  triggerRef?: React.RefObject<HTMLElement | null>
}

export function SubgroupDropdown({
  isOpen,
  existingSubgroups,
  initialValue = '',
  onCommit,
  onCancel,
  variant = 'floating',
  triggerRef,
}: SubgroupDropdownProps) {
  const [draft, setDraft] = useState(initialValue)
  const ref = useRef<HTMLDivElement>(null)

  // Sync draft when opening
  useEffect(() => {
    if (isOpen) setDraft(initialValue)
  }, [isOpen, initialValue])

  // Click outside to cancel
  useEffect(() => {
    if (!isOpen) return
    const onMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onCancel()
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [isOpen, onCancel])

  if (!isOpen) return null

  const others = existingSubgroups.filter((s) => s !== initialValue)
  const isAttached = variant === 'attached'

  return (
    <div
      ref={ref}
      className={
        isAttached
          ? 'absolute left-0 top-full z-50 w-full rounded-b border border-border border-t-0 bg-card shadow-2xl shadow-shade/40 overflow-hidden'
          : 'absolute left-0 top-full mt-1 z-50 w-52 rounded-md border border-border bg-card shadow-2xl shadow-shade/40 overflow-hidden'
      }
    >
      {others.length > 0 && (
        <div className="py-1">
          <div className="px-3 pt-2 pb-1 text-xs font-semibold text-muted-foreground">Existing</div>
          {others.map((sv) => (
            <button
              key={sv}
              onClick={() => onCommit(sv)}
              className="flex w-full items-center px-3 py-1.5 text-xs text-foreground hover:bg-primary/10 hover:text-primary transition-colors capitalize text-left"
            >
              {sv}
            </button>
          ))}
          <div className="h-px bg-border/50 mx-2 mt-1" />
        </div>
      )}
      <div className="p-2">
        <div className="flex gap-1.5">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Rename…"
            maxLength={MAX_NAME_LENGTH}
            autoFocus
            className="flex-1 min-w-0 h-6 px-2 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground"
            onKeyDown={(e) =>
              onInlineEditKey(e, {
                onEnter: () => {
                  if (!draft.trim()) return
                  triggerRef?.current?.focus()
                  onCommit(draft.trim())
                },
                onEscape: () => {
                  triggerRef?.current?.focus()
                  onCancel()
                },
              })
            }
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-6 text-xs flex-shrink-0"
            onClick={() => {
              if (draft.trim()) onCommit(draft.trim())
            }}
          >
            Set
          </Button>
        </div>
      </div>
    </div>
  )
}
