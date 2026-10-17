import { useState } from 'react'
import { getThumbnailUrl } from '@/lib/api'
import { VideoIndicator } from '@/components/ui/video-indicator'
import type { Image } from '@/types'

export interface SceneTileProps {
  image: Image
  /** Primary title line — group name or image name */
  primaryText: string
  /** Second line — subgroup · details, or grid dimensions */
  secondaryText?: string
  /** Third line — author */
  authorText?: string
  onClick: () => void
  /** When true, renders a selection ring. Default false. */
  isActive?: boolean
}

export function SceneTile({
  image,
  primaryText,
  secondaryText,
  authorText,
  onClick,
  isActive = false,
}: SceneTileProps) {
  const [loaded, setLoaded] = useState(false)
  const [errored, setErrored] = useState(false)

  // Dominant extracted color used as placeholder background while the thumbnail loads,
  // so the card doesn't flash harsh grey before the image appears.
  const placeholderBg = image.colors?.[0]?.color_hex ?? undefined

  return (
    <div
      data-testid="scene-tile"
      className={`group relative cursor-pointer overflow-hidden rounded-lg bg-card transition-[transform,box-shadow] duration-200 ${
        isActive
          ? 'border border-primary/60 ring-2 ring-primary/70 shadow-lg shadow-primary/15'
          : 'border border-border/30 hover:border-primary/40 hover:shadow-xl hover:shadow-black/40'
      }`}
      onClick={onClick}
    >
      <div
        className="aspect-[4/3] overflow-hidden"
        style={
          !loaded && !errored && placeholderBg ? { backgroundColor: placeholderBg } : undefined
        }
      >
        {/* Shimmer skeleton shown until image loads */}
        {!loaded && !errored && (
          <div className="absolute inset-0 animate-pulse bg-muted/60 pointer-events-none" />
        )}
        <img
          src={getThumbnailUrl(image)}
          alt={primaryText}
          width={240}
          height={180}
          decoding="async"
          className={`h-full w-full object-cover transition-[transform,opacity] duration-300 group-hover:scale-[1.05] ${
            loaded ? 'opacity-100' : 'opacity-0'
          }`}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => {
            setErrored(true)
            setLoaded(true)
          }}
        />
        {image.media_type === 'video' && <VideoIndicator />}
      </div>

      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/50 to-transparent pt-12 pb-3 px-2.5 pointer-events-none">
        <p className="text-[13px] font-medium text-white leading-snug line-clamp-1 drop-shadow">
          {primaryText}
        </p>
        {secondaryText && (
          <p className="text-[11px] text-white/60 truncate mt-0.5">{secondaryText}</p>
        )}
        {authorText && <p className="text-[11px] text-white/60 truncate mt-0.5">{authorText}</p>}
      </div>

      {isActive && (
        <div className="absolute inset-0 ring-2 ring-inset ring-primary/40 rounded-lg pointer-events-none" />
      )}
    </div>
  )
}
