import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef, useState, useEffect } from 'react'
import { getThumbnailUrl } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import type { Image } from '@/types'

interface ImageGridProps {
  images: Image[]
  onImageClick: (image: Image, index: number) => void
}

const IMAGE_SIZE = 200 // Max size per image in pixels
const GAP = 16 // gap-4 = 1rem = 16px
const PADDING = 16 // p-4 = 1rem = 16px

export function ImageGrid({ images, onImageClick }: ImageGridProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const [columnsPerRow, setColumnsPerRow] = useState(6)

  // Calculate how many columns fit based on container width
  useEffect(() => {
    const updateColumns = () => {
      if (parentRef.current) {
        const containerWidth = parentRef.current.clientWidth
        const availableWidth = containerWidth - (PADDING * 2)
        const columns = Math.max(1, Math.floor((availableWidth + GAP) / (IMAGE_SIZE + GAP)))
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

  const rowVirtualizer = useVirtualizer({
    count: Math.ceil(images.length / columnsPerRow),
    getScrollElement: () => parentRef.current,
    estimateSize: () => IMAGE_SIZE + 60 + GAP, // image + metadata bar + gap
    overscan: 5,
    measureElement: (element) => element.getBoundingClientRect().height,
  })

  return (
    <div ref={parentRef} className="h-full overflow-auto p-4">
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
                paddingBottom: `${GAP}px`,
              }}
            >
              <div
                className="grid gap-4"
                style={{
                  gridTemplateColumns: `repeat(${columnsPerRow}, ${IMAGE_SIZE}px)`,
                  justifyContent: 'center'
                }}
              >
                {rowImages.map((image, colIdx) => {
                  const imageIndex = startIdx + colIdx
                  return (
                    <ImageCard
                      key={image.id}
                      image={image}
                      onClick={() => onImageClick(image, imageIndex)}
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

function ImageCard({ image, onClick }: { image: Image; onClick: () => void }) {
  return (
    <div
      className="group relative cursor-pointer overflow-hidden rounded-lg border bg-card transition-all duration-200 hover:scale-[1.03] hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5"
      onClick={onClick}
    >
      <div className="aspect-square overflow-hidden">
        <img
          src={getThumbnailUrl(image)}
          alt={image.name}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      </div>
      {/* Always-visible metadata bar */}
      <div className="px-2.5 py-1.5 bg-card border-t border-border/50">
        <h3 className="font-semibold text-sm text-foreground truncate">
          {image.name}
        </h3>
        <p className="text-xs text-muted-foreground truncate">{image.author}</p>
        {image.tags && image.tags.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {image.tags.slice(0, 3).map((tag) => (
              <Badge
                key={tag.id}
                variant="outline"
                className="text-[10px] text-muted-foreground"
              >
                {tag.value}
              </Badge>
            ))}
            {image.tags.length > 3 && (
              <Badge
                variant="outline"
                className="text-[10px] text-muted-foreground"
              >
                +{image.tags.length - 3}
              </Badge>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
