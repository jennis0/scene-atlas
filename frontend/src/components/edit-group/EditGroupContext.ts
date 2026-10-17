import { createContext, useContext } from 'react'
import type { ActiveDragState } from '@/components/import/shared/dnd'
import type { UseEditGroupOperationsReturn } from '@/hooks/useEditGroupOperations'
import type { EditableGroupState } from '@/types'
import type { PendingConfirm, SetPendingConfirm } from './pendingConfirm'

/** State the edit dialog shares with its sidebar, file grid, footer and confirmations. */
export interface EditGroupContextValue {
  groups: EditableGroupState[]
  selectedGroupIds: Set<string>
  clearSelection: () => void
  pending: PendingConfirm | null
  setPending: SetPendingConfirm
  activeDrag: ActiveDragState | null
  ops: UseEditGroupOperationsReturn
}

export const EditGroupContext = createContext<EditGroupContextValue | null>(null)

export function useEditGroupContext(): EditGroupContextValue {
  const value = useContext(EditGroupContext)
  if (!value) throw new Error('useEditGroupContext must be used inside EditGroupDialog')
  return value
}
