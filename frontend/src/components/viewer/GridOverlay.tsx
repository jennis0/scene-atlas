import { useEffect, useState, type RefObject } from 'react'

interface GridOverlayProps {
  /** The rendered image the grid is drawn over */
  imageRef: RefObject<HTMLImageElement>
  /** Number of grid columns and rows across the whole image */
  columns: number
  rows: number
}

interface Box {
  left: number
  top: number
  width: number
  height: number
}

/**
 * Draws the image's detected square grid over it. The image keeps its aspect ratio inside
 * the stage, so the overlay tracks the image's rendered box rather than the stage.
 */
export function GridOverlay({ imageRef, columns, rows }: GridOverlayProps) {
  const [box, setBox] = useState<Box | null>(null)

  useEffect(() => {
    const img = imageRef.current
    if (!img) return
    const measure = () =>
      setBox(
        img.naturalWidth
          ? {
              left: img.offsetLeft,
              top: img.offsetTop,
              width: img.offsetWidth,
              height: img.offsetHeight,
            }
          : null,
      )
    measure()
    img.addEventListener('load', measure)
    const observer = new ResizeObserver(measure)
    observer.observe(img)
    return () => {
      img.removeEventListener('load', measure)
      observer.disconnect()
    }
  }, [imageRef])

  if (!box) return null

  const lines: string[] = []
  for (let c = 1; c < columns; c++) lines.push(`M${c} 0V${rows}`)
  for (let r = 1; r < rows; r++) lines.push(`M0 ${r}H${columns}`)
  const d = lines.join('')

  return (
    <svg
      data-testid="grid-overlay"
      aria-hidden="true"
      className="pointer-events-none absolute"
      style={box}
      viewBox={`0 0 ${columns} ${rows}`}
      preserveAspectRatio="none"
    >
      {/* A dark line under a light one keeps the grid visible on any map */}
      <path d={d} stroke="rgb(0 0 0 / 0.45)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      <path
        d={d}
        stroke="rgb(255 255 255 / 0.7)"
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
