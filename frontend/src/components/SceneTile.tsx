import { useState, type ReactNode } from 'react'
import { getThumbnailUrl } from '@/lib/api'
import { VideoIndicator } from '@/components/ui/video-indicator'
import { FileMissingMark } from '@/components/FileMissingMark'
import type { Image } from '@/types'

export interface SceneTileProps {
  image: Image
  /** First line — group name or image name */
  primaryText: string
  /** Second line — subgroup · image name, in the same serif as the viewer's title */
  variantText?: string
  /** Second line — subgroup · details, or grid dimensions */
  secondaryText?: string
  /** Third line — author */
  authorText?: string
  onClick: () => void
  /** When true, renders a selection ring. Default false. */
  isActive?: boolean
  /** Actions menu for the top-right corner (a `CardActionsMenu`) */
  menu?: ReactNode
}

export function SceneTile({
  image,
  primaryText,
  variantText,
  secondaryText,
  authorText,
  onClick,
  isActive = false,
  menu,
}: SceneTileProps) {
  const [loaded, setLoaded] = useState(false)
  const [errored, setErrored] = useState(false)

  // Dominant extracted color used as placeholder background while the thumbnail loads,
  // so the card doesn't flash harsh grey before the image appears.
  const placeholderBg = image.colors?.[0]?.color_hex ?? undefined

  // One spoken name for the tile; the visible caption and image stay out of the
  // accessibility tree so it isn't read twice.
  const missing = image.file_state === 'missing'
  const label = [
    primaryText,
    variantText,
    secondaryText,
    authorText && `by ${authorText}`,
    missing && 'file missing',
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div
      data-testid="scene-tile"
      className={`focus-ring-within group/card relative overflow-hidden rounded-lg bg-card transition-[transform,box-shadow] duration-200 ${
        isActive
          ? 'border border-primary/60 ring-2 ring-primary/70 shadow-lg shadow-primary/15'
          : 'border border-border/30 hover:border-primary/40 hover:shadow-xl hover:shadow-shade/40'
      }`}
    >
      <div
        className="transparency-backdrop aspect-[4/3] overflow-hidden"
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
          alt=""
          width={240}
          height={180}
          decoding="async"
          className={`h-full w-full object-cover transition-[transform,opacity] duration-300 ${
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
        {missing && <FileMissingMark />}
      </div>

      <div
        aria-hidden="true"
        className="caption-scrim absolute inset-x-0 bottom-0 pb-3 px-2.5 pointer-events-none"
      >
        {/* Same type as the viewer: serif names (group heavier than variant), sans details.
            Names wrap to two lines rather than cutting off mid-word. */}
        <p className="font-display text-sm font-semibold text-white leading-tight line-clamp-2 break-words drop-shadow">
          {primaryText}
        </p>
        {variantText && (
          <p className="font-display text-xs text-white/85 hc:text-white leading-snug line-clamp-2 break-words mt-0.5">
            {variantText}
          </p>
        )}
        {secondaryText && (
          <p className="text-2xs text-white/85 hc:text-white truncate mt-0.5">{secondaryText}</p>
        )}
        {authorText && (
          <p className="text-2xs text-white/85 hc:text-white truncate mt-0.5">{authorText}</p>
        )}
      </div>

      {/* Covers the whole tile: the tile's single click and keyboard target */}
      <button
        type="button"
        aria-label={label}
        aria-current={isActive || undefined}
        onClick={onClick}
        className="absolute inset-0 z-[1] cursor-pointer rounded-lg focus-visible:outline-none"
      />

      {menu}

      {isActive && (
        <div className="absolute inset-0 ring-2 ring-inset ring-primary/40 rounded-lg pointer-events-none" />
      )}
    </div>
  )
}
