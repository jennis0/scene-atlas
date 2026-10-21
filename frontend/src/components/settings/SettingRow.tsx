import { ReactNode, useId } from 'react'
import { RestartBadge, type RestartPromptProps } from './RestartBadge'
import { SettingRowContext } from './settingRowContext'

interface SettingRowProps {
  label: string
  description?: string
  /** The setting applies only after a restart */
  restart?: RestartPromptProps
  /** Control below the text instead of beside it: for wide controls (segmented choices,
   * pickers) that would otherwise squeeze the description. */
  stacked?: boolean
  children: ReactNode
}

export function SettingRow({
  label,
  description,
  restart,
  stacked = false,
  children,
}: SettingRowProps) {
  const descriptionId = useId()
  return (
    <div
      className={
        stacked
          ? 'space-y-2 py-0.5'
          : `flex justify-between gap-4 py-1 ${description || restart ? 'items-start' : 'items-center'}`
      }
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{label}</p>
        {description && (
          <p id={descriptionId} className="mt-0.5 text-xs leading-snug text-muted-foreground">
            {description}
          </p>
        )}
        {restart && (
          <div className={restart.pending ? 'mt-2' : 'mt-1'}>
            <RestartBadge {...restart} />
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
