import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef, useState, useEffect } from 'react'
import { Play } from 'lucide-react'
import { getThumbnailUrl } from '@/lib/api'
import type { Image } from '@/types'

interface ImageGridProps {
  images: Image[]
  onImageClick: (image: Image, index: number) => void
}

const IMAGE_SIZE = 240  // card width in pixels
const CARD_HEIGHT = 180 // card height — 4:3 landscape ratio (240 × 0.75)
const GAP = 16          // gap-4 = 1rem = 16px
const PADDING = 16      // p-4 = 1rem = 16px

export function ImageGrid({ images, onImageClick }: ImageGridProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const [columnsPerRow, setColumnsPerRow] = useState(6)

  useEffect(() => {
    const updateColumns = () => {
      if (parentRef.current) {
        const containerWidth = parentRef.current.clientWidth
        const availableWidth = containerWidth - PADDING * 2
        const columns = Math.max(1, Math.floor((availableWidth + GAP) / (IMAGE_SIZE + GAP)))
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
    estimateSize: () => CARD_HEIGHT + GAP,
    overscan: 5,
    measureElement: (element) => element.getBoundingClientRect().height,
  })

  return (
    <div ref={parentRef} className="h-full overflow-auto pt-8 px-4 pb-4">
      <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}>
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
                  justifyContent: 'center',
                }}
              >
                {rowImages.map((image, colIdx) => (
                  <ImageCard
                    key={image.id}
                    image={image}
                    onClick={() => onImageClick(image, startIdx + colIdx)}
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

function ImageCard({ image, onClick }: { image: Image; onClick: () => void }) {
  const [loaded, setLoaded] = useState(false)
  const [errored, setErrored] = useState(false)

  // Use the most dominant extracted color as the placeholder background so
  // the card doesn't flash a harsh grey before the thumbnail loads.
  const placeholderBg = image.colors?.[0]?.color_hex ?? undefined

  // When in a group: primary = group name; secondary = sub-variant + image name (if distinct)
  // When standalone: primary = image name; no secondary
  const primaryText = image.variant_group_name ?? image.name
  const secondaryText = image.variant_group_name
    ? [image.sub_variant, image.name !== image.variant_group_name ? image.name : null]
        .filter(Boolean)
        .join(' · ')
    : ''

  return (
    <div
      className="group relative cursor-pointer overflow-hidden rounded-lg border border-border/30 bg-card transition-all duration-200 hover:border-primary/40 hover:shadow-xl hover:shadow-black/40"
      onClick={onClick}
    >
      {/* Image — 4:3 landscape, scales subtly on hover */}
      <div
        className="aspect-[4/3] overflow-hidden"
        style={!loaded && !errored && placeholderBg ? { backgroundColor: placeholderBg } : undefined}
      >
        {/* Shimmer skeleton shown until the image loads */}
        {!loaded && !errored && (
          <div className="absolute inset-0 animate-pulse bg-muted/60" />
        )}
        <img
          src={getThumbnailUrl(image)}
          alt={image.name}
          className={`h-full w-full object-cover transition-all duration-300 group-hover:scale-[1.05] ${loaded ? 'opacity-100' : 'opacity-0'}`}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => { setErrored(true); setLoaded(true) }}
        />
        {image.media_type === 'video' && (
          <div className="absolute top-2 left-2 z-10 flex items-center justify-center h-6 w-6 rounded-full bg-black/60 text-white/90 backdrop-blur-sm">
            <Play className="h-3 w-3 fill-current" />
          </div>
        )}
      </div>

      {/* Gradient overlay */}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/50 to-transparent pt-12 pb-3 px-2.5 pointer-events-none">
        <p className="text-[13px] font-medium text-white leading-snug line-clamp-1 drop-shadow">
          {primaryText}
        </p>
        {secondaryText && (
          <p className="text-[11px] text-white/60 truncate mt-0.5">{secondaryText}</p>
        )}
        {image.author && (
          <p className="text-[11px] text-white/60 truncate mt-0.5">{image.author}</p>
        )}
      </div>
    </div>
  )
}
