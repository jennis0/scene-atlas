import type { ReactNode } from 'react'

interface GroupSidebarShellProps {
  headerLabel: string
  allCount: number
  isAllActive: boolean
  onSelectAll: () => void
  footer?: ReactNode
  children: ReactNode
}

export function GroupSidebarShell({
  headerLabel,
  allCount,
  isAllActive,
  onSelectAll,
  footer,
  children,
}: GroupSidebarShellProps) {
  return (
    <div className="w-[190px] shrink-0 border-r border-border/30 flex flex-col overflow-hidden bg-muted/20">
      <div className="px-3 py-2.5 border-b border-border/30 shrink-0">
        <span className="text-xs text-muted-foreground font-semibold">{headerLabel}</span>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        <button
          onClick={onSelectAll}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 ${
            isAllActive
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
          }`}
        >
          <span className="font-display text-[15px] font-semibold flex-1">All</span>
          <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">
            {allCount}
          </span>
        </button>
        <div className="h-px bg-border/30 mx-3 my-0.5" />

        {children}
      </div>

      {footer}
    </div>
  )
}
