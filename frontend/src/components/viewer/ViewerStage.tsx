import { ChevronLeft, ChevronRight } from 'lucide-react'
import { getImageUrl } from '@/lib/api'
import type { Image } from '@/types'

// Dot-grid canvas background — gives the image a defined "stage"
const CANVAS_STYLE: React.CSSProperties = {
  background: 'hsl(var(--surface-canvas))',
  backgroundImage: 'radial-gradient(circle, hsl(var(--foreground) / 0.045) 1px, transparent 1px)',
  backgroundSize: '24px 24px',
}

const NAV_BUTTON =
  'absolute top-1/2 -translate-y-1/2 h-10 w-10 rounded-full bg-black/50 hover:bg-black/75 text-white/80 hover:text-white flex items-center justify-center transition-all'

interface ViewerStageProps {
  image: Image
  onPrevious?: () => void
  onNext?: () => void
}

export function ViewerStage({ image, onPrevious, onNext }: ViewerStageProps) {
  return (
    <div
      className="h-[45vh] shrink-0 lg:h-auto lg:flex-1 relative flex items-center justify-center min-w-0"
      style={CANVAS_STYLE}
    >
      {/* Amber stripe — canvas half: transparent at left edge, full at join */}
      <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent to-primary/80 pointer-events-none z-10" />

      {image.media_type === 'video' ? (
        <video
          key={image.id}
          src={getImageUrl(image)}
          controls
          autoPlay
          loop
          className="max-h-full max-w-full object-contain shadow-2xl shadow-black/60"
        />
      ) : (
        <img
          src={getImageUrl(image)}
          alt={image.name}
          className="max-h-full max-w-full object-contain shadow-2xl shadow-black/60"
        />
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
