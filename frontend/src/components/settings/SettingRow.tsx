import { ReactNode, useId } from 'react'
import { RestartBadge } from './RestartBadge'
import { SettingRowContext } from './settingRowContext'

interface SettingRowProps {
  label: string
  description?: string
  requiresRestart?: boolean
  /** Control below the text instead of beside it: for wide controls (segmented choices,
   * pickers) that would otherwise squeeze the description. */
  stacked?: boolean
  children: ReactNode
}

export function SettingRow({
  label,
  description,
  requiresRestart,
  stacked = false,
  children,
}: SettingRowProps) {
  const descriptionId = useId()
  return (
    <div
      className={
        stacked
          ? 'space-y-2 py-0.5'
          : `flex justify-between gap-4 py-1 ${description || requiresRestart ? 'items-start' : 'items-center'}`
      }
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{label}</p>
        {description && (
          <p id={descriptionId} className="mt-0.5 text-xs leading-snug text-muted-foreground">
            {description}
          </p>
        )}
        {requiresRestart && (
          <div className="mt-2">
            <RestartBadge />
          </div>
        )}
      </div>
      {/* Stacked: a flex column, so inline controls keep their own width */}
      <div className={stacked ? 'flex flex-col items-start' : 'flex-shrink-0'}>
        {/* Controls that read this describe themselves with the row's description */}
        <SettingRowContext.Provider
          value={{ descriptionId: description ? descriptionId : undefined }}
        >
          {children}
        </SettingRowContext.Provider>
      </div>
    </div>
  )
}
