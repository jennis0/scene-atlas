import { useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { SidebarRow } from './sidebarRows'

/** A sidebar row's height before it's measured. */
const ROW_ESTIMATE = 36

interface SidebarListProps {
  rows: SidebarRow[]
  scrollElement: HTMLDivElement | null
  render: (row: SidebarRow) => React.ReactNode
}

/** From this many rows the list is windowed; below it, rendered whole. */
const WINDOW_FROM = 100

/** The group rows. A large import lists thousands of groups, so long lists are windowed. */
export function SidebarList(props: SidebarListProps) {
  // (Comparisons written with >=: lizard, behind Codacy's complexity check, reads a
  // "<" in a .tsx file as a JSX tag and then misparses the rest of the file)
  if (props.rows.length >= WINDOW_FROM) return <WindowedSidebarList {...props} />
  return props.rows.map((row) => <div key={row.key}>{props.render(row)}</div>)
}

function offsetTopOf(el: HTMLElement | null) {
  if (!el) return 0
  return el.offsetTop
}

function WindowedSidebarList({ rows, scrollElement, render }: SidebarListProps) {
  const [listElement, setListElement] = useState<HTMLDivElement | null>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => ROW_ESTIMATE,
    getItemKey: (i) => rows[i].key,
    // The All row sits above the list in the same scroll area
    scrollMargin: offsetTopOf(listElement),
    overscan: 8,
  })

  return (
    <div
      ref={setListElement}
      className="relative w-full"
      style={{ height: virtualizer.getTotalSize() }}
    >
      {virtualizer.getVirtualItems().map((item) => {
        const top = item.start - virtualizer.options.scrollMargin
        return (
          <div
            key={item.key}
            data-index={item.index}
            ref={virtualizer.measureElement}
            className="absolute left-0 top-0 w-full"
            style={{ transform: `translateY(${top}px)` }}
          >
            {render(rows[item.index])}
          </div>
        )
      })}
    </div>
  )
}
