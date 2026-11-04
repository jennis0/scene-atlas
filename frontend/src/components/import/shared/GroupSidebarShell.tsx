import type { ReactNode } from 'react'
import { ImageOff } from 'lucide-react'

/** The "All" row at the top of the sidebar */
export interface AllTab {
  active: boolean
  /** Files in scope across every group */
  count: number
  onSelect: () => void
}

/** Import review: the images Auto skipped that no group claims, under the groups */
export interface SkippedTab {
  active: boolean
  count: number
  onSelect: () => void
}

const TAB_STATE = {
  active: 'border-primary bg-primary/10 text-primary',
  idle: 'border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/50',
}

interface GroupSidebarShellProps {
  headerLabel: string
  allTab: AllTab
  skippedTab?: SkippedTab
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
  skippedTab,
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
            allTab.active ? TAB_STATE.active : TAB_STATE.idle
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

      {skippedTab && (
        <button
          onClick={skippedTab.onSelect}
          aria-current={skippedTab.active ? 'true' : undefined}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors border-l-2 border-t border-t-border/30 shrink-0 ${
            skippedTab.active ? TAB_STATE.active : TAB_STATE.idle
          }`}
        >
          <ImageOff className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="text-sm flex-1">Skipped by Auto</span>
          <span className="text-2xs text-muted-foreground tabular-nums shrink-0">
            {skippedTab.count.toLocaleString()}
          </span>
        </button>
      )}

      {footer}
    </div>
  )
}
