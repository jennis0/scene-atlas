import type { EditableFileState } from '@/types'

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
  const cls = small ? 'w-20' : 'w-[140px]'
  const filter = dimmed ? 'grayscale(0.6)' : undefined

  return (
    <button
      type="button"
      className={`${cls} shrink-0 relative overflow-hidden rounded-l-lg bg-secondary cursor-zoom-in min-h-[80px]`}
      style={{ filter }}
      onClick={() => {
        if (previewUrl) onOpenLightbox()
      }}
      tabIndex={-1}
    >
      {useVideoThumb ? (
        <video
          src={previewUrl}
          muted
          preload="metadata"
          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
        />
      ) : (
        <img
          src={previewUrl}
          alt={file.filename}
          loading="lazy"
          className="absolute inset-0 w-full h-full object-cover pointer-events-none transition-transform duration-300 group-hover/card:scale-[1.04]"
          onError={(e) => {
            const el = e.target as HTMLImageElement
            el.style.display = 'none'
            el.parentElement!.classList.add('flex', 'items-center', 'justify-center')
            const placeholder = document.createElement('span')
            placeholder.className =
              'text-[10px] text-muted-foreground/40 font-medium text-center px-1'
            placeholder.textContent = 'No preview'
            el.parentElement!.appendChild(placeholder)
          }}
        />
      )}
      {/* Selection checkbox overlay */}
      {!dimmed && !hideCheckbox && (
        <div
          className={`absolute top-1.5 left-1.5 w-4 h-4 rounded-[3px] flex items-center justify-center text-[9px] transition-all backdrop-blur-sm ${
            selected
              ? 'bg-primary/90 border-primary text-primary-foreground font-bold'
              : 'bg-black/35 border-white/20 text-transparent'
          } border-[1.5px]`}
        >
          ✓
        </div>
      )}
    </button>
  )
}
