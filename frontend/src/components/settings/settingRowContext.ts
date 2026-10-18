import { createContext, useContext } from 'react'

/** Ids a SettingRow gives its control, so the control can point at the row's description
 * (aria-describedby) and screen readers read it with the control. */
export const SettingRowContext = createContext<{ descriptionId?: string }>({})

export function useSettingRowDescriptionId(): string | undefined {
  return useContext(SettingRowContext).descriptionId
}
