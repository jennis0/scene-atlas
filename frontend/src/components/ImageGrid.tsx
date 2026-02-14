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
    estimateSize: () => IMAGE_SIZE + GAP,
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
      className="group relative cursor-pointer overflow-hidden rounded-lg border bg-card transition-transform hover:scale-105"
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
      <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 transition-opacity group-hover:opacity-100">
        <div className="absolute bottom-0 left-0 right-0 p-3">
          <h3 className="font-semibold text-white text-sm truncate">
            {image.name}
          </h3>
          <p className="text-xs text-white/80">{image.author}</p>
          {image.tags && image.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {image.tags.slice(0, 3).map((tag) => (
                <Badge key={tag.id} variant="secondary" className="text-xs">
                  {tag.value}
                </Badge>
              ))}
              {image.tags.length > 3 && (
                <Badge variant="secondary" className="text-xs">
                  +{image.tags.length - 3}
                </Badge>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
