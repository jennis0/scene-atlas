import { useState, useEffect, useMemo } from 'react'
import { Layers } from 'lucide-react'
import { GroupPickerShell } from '@/components/GroupPickerShell'
import type { EditableGroupState } from '@/types'

interface ImportMergeGroupPickerProps {
  open: boolean
  onClose: () => void
  groups: EditableGroupState[]
  sourceIndex: number
  onSelect: (targetIndex: number) => void
  currentGroupName?: string
}

export function ImportMergeGroupPicker({
  open,
  onClose,
  groups,
  sourceIndex,
  onSelect,
  currentGroupName,
}: ImportMergeGroupPickerProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)

  useEffect(() => {
    if (open) {
      setSearchQuery('')
      setSelectedIndex(null)
    }
  }, [open])

  const targets = useMemo(() => {
    const filtered = groups
      .map((g, i) => ({ group: g, index: i }))
      .filter(({ index }) => index !== sourceIndex)
    if (!searchQuery.trim()) return filtered
    const q = searchQuery.toLowerCase()
    return filtered.filter(({ group }) => group.group_name.toLowerCase().includes(q))
  }, [groups, sourceIndex, searchQuery])

  return (
    <GroupPickerShell
      open={open}
      onClose={onClose}
      title={`Merge \u201c${currentGroupName}\u201d into\u2026`}
      searchQuery={searchQuery}
      onSearchChange={setSearchQuery}
      confirmDisabled={selectedIndex === null}
      onConfirm={() => selectedIndex !== null && onSelect(selectedIndex)}
    >
      {targets.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-[200px] text-muted-foreground/50">
          <Layers className="h-8 w-8 mb-2 opacity-40" />
          <p className="text-sm">No matching groups</p>
        </div>
      ) : (
        <div className="space-y-px">
          {targets.map(({ group, index }) => {
            const isSelected = selectedIndex === index
            const fileCount = group.files.filter((f) => !f.excluded).length
            return (
              <button
                key={group.id}
                onClick={() => setSelectedIndex(index)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-all duration-100 ${
                  isSelected ? 'bg-primary/15 ring-1 ring-primary/40' : 'hover:bg-muted/50'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <p className={`text-[13px] font-medium leading-tight truncate ${isSelected ? 'text-primary' : 'text-foreground'}`}>
                    {group.group_name}
                  </p>
                </div>
                <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground/50 bg-muted/40 px-1.5 py-0.5 rounded">
                  {fileCount}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </GroupPickerShell>
  )
}
