import { useEffect, useRef, type ReactNode } from 'react'
import { Search, Merge } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

interface GroupPickerShellProps {
  open: boolean
  onClose: () => void
  title: string
  searchQuery: string
  onSearchChange: (query: string) => void
  confirmDisabled: boolean
  onConfirm: () => void
  confirmLabel?: string
  confirmIcon?: ReactNode
  children: ReactNode
}

export function GroupPickerShell({
  open,
  onClose,
  title,
  searchQuery,
  onSearchChange,
  confirmDisabled,
  onConfirm,
  confirmLabel = 'Merge',
  confirmIcon,
  children,
}: GroupPickerShellProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50)
  }, [open])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md p-0 overflow-hidden gap-0" onClose={onClose}>
        <DialogHeader className="px-5 pt-5 pb-0">
          <DialogTitle className="text-[15px] tracking-wide">{title}</DialogTitle>
        </DialogHeader>

        <div className="px-5 pt-3 pb-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/60" />
            <input
              ref={inputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search groups..."
              className="w-full h-8 pl-8 pr-3 text-sm bg-secondary border border-border rounded-md text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40 transition-colors"
            />
          </div>
        </div>

        <div className="min-h-[200px] max-h-[320px] overflow-y-auto px-2 pb-2 scrollbar-thin">
          {children}
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-border/30 bg-muted/10">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md border border-border/50 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={confirmDisabled}
            className="px-4 py-1.5 text-sm rounded-md font-medium bg-primary/90 text-primary-foreground hover:bg-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {confirmIcon ?? <Merge className="h-3.5 w-3.5" />}
            {confirmLabel}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
