import { ReactNode } from 'react'
import { RestartBadge } from './RestartBadge'

interface SettingRowProps {
  label: string
  description?: string
  requiresRestart?: boolean
  children: ReactNode
}

export function SettingRow({ label, description, requiresRestart, children }: SettingRowProps) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="flex-1 min-w-0">
        <p className="section-label mb-1">{label}</p>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
        {requiresRestart && (
          <div className="mt-2">
            <RestartBadge />
          </div>
        )}
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  )
}
