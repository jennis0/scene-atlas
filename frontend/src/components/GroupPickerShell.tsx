import { type ReactNode } from 'react'
import { Search, Merge, X } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PanelTitle } from '@/components/ui/panel-title'

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
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-[440px] bg-card border-border/50 p-0 gap-0 overflow-hidden flex flex-col relative">
        <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-primary/70 via-primary/30 to-transparent pointer-events-none rounded-t-lg" />

        {/* Header: bg-popover strip with title and close button */}
        <div className="px-4 py-2.5 border-b border-border/30 bg-popover flex items-center justify-between shrink-0 relative">
          <PanelTitle className="flex-1">{title}</PanelTitle>
          <button
            onClick={onClose}
            className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors shrink-0 ml-2"
          >
            <X className="h-3.5 w-3.5" />
            <span className="sr-only">Close</span>
          </button>
        </div>

        <div className="px-4 pt-3 pb-2 shrink-0">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
            <Input
              data-autofocus
              inputSize="compact"
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search groups…"
              className="pl-8"
            />
          </div>
        </div>

        <div className="min-h-[200px] max-h-[320px] overflow-y-auto px-2 pb-2 scrollbar-thin flex-1">
          {children}
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-border/30 bg-muted/5 shrink-0">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md border border-border/50 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={confirmDisabled}
            className="px-3.5 py-1.5 text-sm rounded-md border font-medium flex items-center gap-1.5 transition-colors
              border-primary/30 bg-primary/10 text-primary hover:bg-primary/20
              disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {confirmIcon ?? <Merge className="h-3.5 w-3.5" />}
            {confirmLabel}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
