import { useContext, type ReactNode } from 'react'
import { DialogTitleIdContext } from './dialogTitleId'

interface PanelTitleProps {
  children: ReactNode
  /** Inline status next to the title, e.g. a count pill. */
  badge?: ReactNode
  className?: string
}

/**
 * The small display-font title used on panels and compact dialogs.
 * Inside a DialogContent it becomes the dialog's heading and accessible name.
 */
export function PanelTitle({ children, badge, className = '' }: PanelTitleProps) {
  const dialogTitleId = useContext(DialogTitleIdContext)
  return (
    <div className={`flex flex-col ${className}`}>
      <div className="flex items-center gap-2">
        <h2
          id={dialogTitleId}
          className="font-display text-sm font-medium text-foreground leading-none"
        >
          {children}
        </h2>
        {badge}
      </div>
    </div>
  )
}
