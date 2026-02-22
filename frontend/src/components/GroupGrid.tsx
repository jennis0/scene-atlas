import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef, useState, useEffect } from 'react'
import { GroupCard } from '@/components/GroupCard'
import type { ImageGroup } from '@/types'

interface GroupGridProps {
  groups: ImageGroup[]
  onGroupClick: (group: ImageGroup) => void
  onEditGroup?: (group: ImageGroup) => void
  onDeleteGroup?: (group: ImageGroup) => void
  onMergeGroup?: (group: ImageGroup) => void
}

const CARD_WIDTH = 420
const CARD_HEIGHT = 160 // image area only — metadata lives in gradient overlay
const GAP = 24
const PADDING = 16

export function GroupGrid({
  groups,
  onGroupClick,
  onEditGroup,
  onDeleteGroup,
  onMergeGroup,
}: GroupGridProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const [columnsPerRow, setColumnsPerRow] = useState(3)

  useEffect(() => {
    const updateColumns = () => {
      if (parentRef.current) {
        const availableWidth = parentRef.current.clientWidth - PADDING * 2
        const columns = Math.max(1, Math.floor((availableWidth + GAP) / (CARD_WIDTH + GAP)))
        setColumnsPerRow(columns)
      }
    }

    updateColumns()
    const resizeObserver = new ResizeObserver(updateColumns)
    if (parentRef.current) {
      resizeObserver.observe(parentRef.current)
    }
    return () => resizeObserver.disconnect()
  }, [])

  const rowCount = Math.ceil(groups.length / columnsPerRow)

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => CARD_HEIGHT + GAP,
    overscan: 5,
  })

  return (
    <div ref={parentRef} className="h-full overflow-auto pt-8 px-4 pb-4">
      <div
        style={{
          height: `${rowVirtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const startIdx = virtualRow.index * columnsPerRow
          const rowGroups = groups.slice(startIdx, startIdx + columnsPerRow)

          return (
            <div
              key={virtualRow.key}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
                paddingBottom: `${GAP}px`,
              }}
            >
              <div
                className="grid gap-4"
                style={{
                  gridTemplateColumns: `repeat(${columnsPerRow}, ${CARD_WIDTH}px)`,
                  justifyContent: 'center',
                }}
              >
                {rowGroups.map((group) => (
                  <GroupCard
                    key={group.groupId ?? `solo-${group.heroImage.id}`}
                    group={group}
                    onClick={() => onGroupClick(group)}
                    onEdit={() => onEditGroup?.(group)}
                    onDelete={() => onDeleteGroup?.(group)}
                    onMerge={() => onMergeGroup?.(group)}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
