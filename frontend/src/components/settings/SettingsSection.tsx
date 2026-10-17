import type { ReactNode } from 'react'

interface SettingsSectionProps {
  title: string
  description?: string
  /** Draw the divider under the section (every section but the last). */
  divider?: boolean
  children: ReactNode
}

export function SettingsSection({
  title,
  description,
  divider = true,
  children,
}: SettingsSectionProps) {
  return (
    <section className="space-y-3">
      {/* Section titles in the book serif, above the sans row labels */}
      <h3 className="-mb-1 font-display text-lg font-semibold text-foreground">{title}</h3>
      {description && <p className="text-xs text-muted-foreground -mt-2 mb-2">{description}</p>}
      {children}
      {divider && <div className="border-t border-border/30" />}
    </section>
  )
}
