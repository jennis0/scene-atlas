import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef, useState, useEffect } from 'react'
import { IMAGE_SIZE, CARD_HEIGHT, GRID_GAP, GRID_PADDING } from '@/lib/constants'
import { SceneTile } from '@/components/SceneTile'
import type { Image } from '@/types'

interface ImageGridProps {
  images: Image[]
  onImageClick: (image: Image, index: number) => void
}

export function ImageGrid({ images, onImageClick }: ImageGridProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const [columnsPerRow, setColumnsPerRow] = useState(6)

  useEffect(() => {
    const updateColumns = () => {
      if (parentRef.current) {
        const containerWidth = parentRef.current.clientWidth
        const availableWidth = containerWidth - GRID_PADDING * 2
        const columns = Math.max(
          1,
          Math.floor((availableWidth + GRID_GAP) / (IMAGE_SIZE + GRID_GAP)),
        )
        setColumnsPerRow(columns)
      }
    }

    updateColumns()
    const resizeObserver = new ResizeObserver(updateColumns)
    if (parentRef.current) resizeObserver.observe(parentRef.current)
    return () => resizeObserver.disconnect()
  }, [])

  const rowVirtualizer = useVirtualizer({
    count: Math.ceil(images.length / columnsPerRow),
    getScrollElement: () => parentRef.current,
    estimateSize: () => CARD_HEIGHT + GRID_GAP,
    overscan: 5,
    measureElement: (element) => element.getBoundingClientRect().height,
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
          const rowImages = images.slice(startIdx, startIdx + columnsPerRow)

          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={rowVirtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
                paddingBottom: `${GRID_GAP}px`,
              }}
            >
              <div
                className="grid gap-4"
                style={{
                  gridTemplateColumns: `repeat(${columnsPerRow}, ${IMAGE_SIZE}px)`,
                  justifyContent: 'center',
                }}
              >
                {rowImages.map((image, colIdx) => {
                  // When in a group: primary = group name; secondary = subgroup + image name (if distinct)
                  // When standalone: primary = image name; no secondary
                  const primaryText = image.group_name ?? image.name
                  const secondaryText = image.group_name
                    ? [image.subgroup, image.name !== image.group_name ? image.name : null]
                        .filter(Boolean)
                        .join(' · ')
                    : undefined

                  return (
                    <SceneTile
                      key={image.id}
                      image={image}
                      primaryText={primaryText}
                      secondaryText={secondaryText || undefined}
                      authorText={image.author || undefined}
                      onClick={() => onImageClick(image, startIdx + colIdx)}
                    />
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
