import { useState } from 'react'
import type { EditableFileState } from '@/types'
import { ZoomIn } from 'lucide-react'
import { VideoIndicator } from '@/components/ui/video-indicator'

interface FileCardThumbnailProps {
  file: EditableFileState
  previewUrl: string
  useVideoThumb: boolean
  selected: boolean
  dimmed?: boolean
  small?: boolean
  hideCheckbox?: boolean
  onOpenLightbox: () => void
}

export function FileCardThumbnail({
  file,
  previewUrl,
  useVideoThumb,
  selected,
  dimmed,
  small,
  hideCheckbox,
  onOpenLightbox,
}: FileCardThumbnailProps) {
  const [imgError, setImgError] = useState(false)
  const cls = small ? 'w-20' : 'w-[140px]'
  const filter = dimmed ? 'grayscale(0.6)' : undefined

  return (
    <div
      className={`${cls} shrink-0 relative overflow-hidden rounded-l-lg bg-secondary min-h-[80px]`}
      style={{ filter }}
    >
      {useVideoThumb ? (
        <video
          src={previewUrl}
          muted
          preload="metadata"
          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
        />
      ) : imgError ? (
        <span className="absolute inset-0 flex items-center justify-center text-3xs text-muted-foreground font-medium text-center px-1">
          No preview
        </span>
      ) : (
        <img
          src={previewUrl}
          alt={file.filename}
          loading="lazy"
          className="absolute inset-0 w-full h-full object-cover pointer-events-none transition-transform duration-300 group-hover/card:scale-[1.04]"
          onError={() => setImgError(true)}
        />
      )}
      {/* Video indicator — bottom-left to avoid checkbox overlap */}
      {file.media_type === 'video' && !dimmed && (
        <VideoIndicator size="sm" className="bottom-1 left-1" />
      )}
      {!dimmed && !hideCheckbox && (
        <div
          className={`absolute top-1.5 left-1.5 w-4 h-4 rounded-[3px] flex items-center justify-center text-3xs transition-all backdrop-blur-sm ${
            selected
              ? 'bg-primary/90 border-primary text-primary-foreground font-bold'
              : 'bg-black/35 border-white/20 text-transparent'
          } border-[1.5px]`}
        >
          ✓
        </div>
      )}
      {/* Magnify icon overlay — top-right, visible on hover */}
      {previewUrl && !dimmed && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onOpenLightbox()
          }}
          className="absolute top-1.5 right-1.5 w-5 h-5 rounded-[3px] flex items-center justify-center bg-black/40 border-[1.5px] border-white/20 text-white/70 opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/card:opacity-100 hover:bg-black/60 hover:text-white transition-all backdrop-blur-sm cursor-zoom-in"
          tabIndex={-1}
        >
          <ZoomIn className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}
