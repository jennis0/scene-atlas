import { useRef } from 'react'
import { ChevronLeft, ChevronRight, Grid3x3 } from 'lucide-react'
import { GridOverlay } from '@/components/viewer/GridOverlay'
import { canShowGrid } from '@/lib/gridOverlay'
import { getImageUrl, getThumbnailUrl } from '@/lib/api'
import type { Image } from '@/types'

const CANVAS_STYLE: React.CSSProperties = { background: 'hsl(var(--surface-canvas))' }

/** Why the original can't be shown; the thumbnail stands in (design/library-setup.md §4.7) */
const UNAVAILABLE: Record<Exclude<Image['file_state'], 'ok'>, string> = {
  missing: 'The original file is missing.',
  offline: "The folder this image is in isn't available.",
}

const NAV_BUTTON =
  'absolute top-1/2 -translate-y-1/2 h-10 w-10 rounded-full bg-black/50 hover:bg-black/75 text-white/80 hc:text-white hover:text-white hc:bg-black/85 hc:text-white hc:ring-1 hc:ring-white/70 flex items-center justify-center transition-all'

interface ViewerStageProps {
  image: Image
  onPrevious?: () => void
  onNext?: () => void
  /** Draw the detected grid over the image, when it has one */
  showGrid: boolean
  onToggleGrid: () => void
}

export function ViewerStage({
  image,
  onPrevious,
  onNext,
  showGrid,
  onToggleGrid,
}: ViewerStageProps) {
  const imageRef = useRef<HTMLImageElement>(null)
  const gridAvailable = canShowGrid(image)
  const unavailable = image.file_state === 'ok' ? null : UNAVAILABLE[image.file_state]
  return (
    <div
      className="h-[45vh] shrink-0 lg:h-auto lg:flex-1 relative flex items-center justify-center min-w-0"
      style={CANVAS_STYLE}
    >
      {unavailable ? (
        <img
          ref={imageRef}
          src={getThumbnailUrl(image)}
          alt={image.name}
          className="max-h-full max-w-full object-contain shadow-2xl shadow-shade/60"
        />
      ) : image.media_type === 'video' ? (
        <video
          key={image.id}
          src={getImageUrl(image)}
          controls
          autoPlay
          loop
          className="max-h-full max-w-full object-contain shadow-2xl shadow-shade/60"
        />
      ) : (
        <img
          ref={imageRef}
          src={getImageUrl(image)}
          alt={image.name}
          className="max-h-full max-w-full object-contain shadow-2xl shadow-shade/60"
        />
      )}
      {unavailable && (
        <p
          role="status"
          className="absolute top-3 left-1/2 -translate-x-1/2 max-w-[calc(100%-1.5rem)] rounded-md bg-black/75 px-3 py-1.5 text-xs text-white forced-colors:border"
        >
          {unavailable}
        </p>
      )}
      {gridAvailable && showGrid && (
        <GridOverlay
          key={image.id}
          imageRef={imageRef}
          columns={image.grid_width!}
          rows={image.grid_height!}
        />
      )}
      {gridAvailable && (
        <button
          type="button"
          aria-pressed={showGrid}
          aria-keyshortcuts="G"
          title={`${showGrid ? 'Hide' : 'Show'} grid (G)`}
          onClick={(e) => {
            e.stopPropagation()
            onToggleGrid()
          }}
          className={`absolute bottom-3 left-3 h-9 px-3 rounded-md flex items-center gap-1.5 text-xs font-medium transition-colors ${
            showGrid
              ? 'bg-white/90 text-black'
              : 'bg-black/50 text-white/90 hc:text-white hover:bg-black/75 hc:bg-black/85 hc:text-white hc:ring-1 hc:ring-white/70'
          }`}
        >
          <Grid3x3 className="h-4 w-4" />
          Grid {image.grid_width}×{image.grid_height}
        </button>
      )}
      {onPrevious && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onPrevious()
          }}
          aria-label="Previous image"
          className={`left-3 ${NAV_BUTTON}`}
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
      )}
      {onNext && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onNext()
          }}
          aria-label="Next image"
          className={`right-3 ${NAV_BUTTON}`}
        >
          <ChevronRight className="h-5 w-5" />
        </button>
      )}
    </div>
  )
}
