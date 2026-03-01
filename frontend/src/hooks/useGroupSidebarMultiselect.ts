import { useState, useCallback } from 'react'
import type { EditableGroupState } from '@/types'

interface UseGroupSidebarMultiselectOptions {
  groups: EditableGroupState[]
  onSelectTab: (tab: number) => void
}

export interface UseGroupSidebarMultiselectReturn {
  selectedGroupIds: Set<string>
  setSelectedGroupIds: React.Dispatch<React.SetStateAction<Set<string>>>
  handleGroupClick: (index: number, groupId: string, event: React.MouseEvent) => void
  resetMultiselect: () => void
}

export function useGroupSidebarMultiselect({
  groups,
  onSelectTab,
}: UseGroupSidebarMultiselectOptions): UseGroupSidebarMultiselectReturn {
  const [selectedGroupIds, setSelectedGroupIds] = useState<Set<string>>(new Set())
  const [lastClickedGroupIndex, setLastClickedGroupIndex] = useState<number | null>(null)

  const handleGroupClick = useCallback(
    (index: number, groupId: string, event: React.MouseEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        setSelectedGroupIds((prev) => {
          const next = new Set(prev)
          if (next.has(groupId)) next.delete(groupId)
          else next.add(groupId)
          return next
        })
        setLastClickedGroupIndex(index)
        return
      }
      if (event.shiftKey && lastClickedGroupIndex !== null) {
        event.preventDefault()
        const start = Math.min(lastClickedGroupIndex, index)
        const end = Math.max(lastClickedGroupIndex, index)
        const rangeIds = groups.slice(start, end + 1).map((g) => g.id)
        setSelectedGroupIds(new Set(rangeIds))
        return
      }
      // Normal click: navigate to group, clear multiselect
      onSelectTab(index)
      setSelectedGroupIds(new Set())
      setLastClickedGroupIndex(index)
    },
    [lastClickedGroupIndex, groups, onSelectTab],
  )

  const resetMultiselect = useCallback(() => {
    setSelectedGroupIds(new Set())
    setLastClickedGroupIndex(null)
  }, [])

  return {
    selectedGroupIds,
    setSelectedGroupIds,
    handleGroupClick,
    resetMultiselect,
  }
}
