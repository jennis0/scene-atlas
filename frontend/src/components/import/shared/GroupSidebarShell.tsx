import type { ReactNode } from 'react'

/** The "All" row at the top of the sidebar */
export interface AllTab {
  active: boolean
  /** Files in scope across every group */
  count: number
  onSelect: () => void
}

interface GroupSidebarShellProps {
  headerLabel: string
  allTab: AllTab
  footer?: ReactNode
  /** Under the header, outside the scrolling list (e.g. a filter) */
  toolbar?: ReactNode
  /** Receives the scrolling list's element, for windowing its rows */
  scrollRef?: (el: HTMLDivElement | null) => void
  children: ReactNode
}

export function GroupSidebarShell({
  headerLabel,
  allTab,
  footer,
  toolbar,
  scrollRef,
  children,
}: GroupSidebarShellProps) {
  return (
    <div className="w-[14rem] shrink-0 border-r border-border/30 flex flex-col overflow-hidden bg-muted/20">
      <div className="px-3 py-2.5 border-b border-border/30 shrink-0">
        <span className="text-xs text-muted-foreground font-semibold">{headerLabel}</span>
      </div>

      {toolbar}

      {/* relative: rows are positioned against it (offsetTop) when windowed */}
      <div ref={scrollRef} className="relative flex-1 overflow-y-auto py-1">
        <button
          onClick={allTab.onSelect}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 ${
            allTab.active
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50'
          }`}
        >
          <span className="font-display text-sm font-semibold flex-1">All</span>
          <span className="text-2xs text-muted-foreground tabular-nums shrink-0">
            {allTab.count.toLocaleString()}
          </span>
        </button>
        <div className="h-px bg-border/30 mx-3 my-0.5" />

        {children}
      </div>

      {footer}
    </div>
  )
}
