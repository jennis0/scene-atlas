import type { ReactNode } from 'react'

interface PanelTitleProps {
  children: ReactNode
  /** Inline status next to the title, e.g. a count pill. */
  badge?: ReactNode
  className?: string
}

/** The small display-font title with an accent underline used on panels and compact dialogs. */
export function PanelTitle({ children, badge, className = '' }: PanelTitleProps) {
  return (
    <div className={`flex flex-col ${className}`}>
      <div className="flex items-center gap-2">
        <span className="font-display text-[13px] font-medium tracking-[0.06em] text-foreground leading-none">
          {children}
        </span>
        {badge}
      </div>
      <div className="mt-[3px] h-px w-7 bg-gradient-to-r from-primary to-transparent" />
    </div>
  )
}
