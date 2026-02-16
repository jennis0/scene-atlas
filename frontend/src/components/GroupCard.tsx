import { getThumbnailUrl } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import type { ImageGroup } from '@/types'

interface GroupCardProps {
  group: ImageGroup
  onClick: () => void
}

export function GroupCard({ group, onClick }: GroupCardProps) {
  const {
    heroImage,
    mosaicImages,
    totalVariants,
    matchingCount,
    baseName,
    author,
    aggregatedTags,
  } = group

  // Cap mosaic to even counts (1, 2, or 4) to avoid empty grid cells
  const maxMosaic = mosaicImages.length >= 4 ? 4 : mosaicImages.length >= 2 ? 2 : mosaicImages.length
  const visibleMosaic = mosaicImages.slice(0, maxMosaic)
  const displayedCount = 1 + visibleMosaic.length
  const overflowCount = totalVariants - displayedCount
  const hasMosaic = visibleMosaic.length > 0

  return (
    <div
      className="group/card relative cursor-pointer overflow-hidden rounded-lg border bg-card transition-all duration-200 hover:scale-[1.03] hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5"
      onClick={onClick}
    >
      {/* Image area */}
      <div className="flex" style={{ height: '160px' }}>
        {/* Hero image */}
        <div
          className="relative h-full shrink-0 overflow-hidden"
          style={{ width: hasMosaic ? '60%' : '100%' }}
        >
          <img
            src={getThumbnailUrl(heroImage)}
            alt={baseName}
            className="h-full w-full object-cover"
            loading="lazy"
          />
          {hasMosaic && (
            <div className="absolute inset-y-0 right-0 w-px bg-black/30" />
          )}
        </div>

        {/* Mosaic grid */}
        {hasMosaic && (
          <div
            className="relative h-full shrink-0 overflow-hidden"
            style={{ width: '40%' }}
          >
            <div className={`grid h-full ${mosaicGridClasses(visibleMosaic.length)}`}>
              {visibleMosaic.map((img, i) => {
                const isOverflowTile =
                  i === visibleMosaic.length - 1 && overflowCount > 0

                return (
                  <div key={img.id} className="relative overflow-hidden">
                    <img
                      src={getThumbnailUrl(img)}
                      alt={img.sub_variant || img.name}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />

                    {/* Sub-variant label */}
                    {img.sub_variant && !isOverflowTile && (
                      <div className="absolute bottom-0 left-0 right-0 bg-black/50 px-1.5 py-0.5">
                        <span className="text-[10px] leading-tight text-white/90 line-clamp-1">
                          {img.sub_variant}
                        </span>
                      </div>
                    )}

                    {/* +N more overlay */}
                    {isOverflowTile && (
                      <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/60 backdrop-blur-[2px]">
                        <span className="text-lg font-bold text-white">
                          +{overflowCount}
                        </span>
                        <span className="text-[10px] text-white/70">more</span>
                      </div>
                    )}

                    {/* Hairline grid separators */}
                    <div className="absolute inset-0 pointer-events-none ring-[0.5px] ring-inset ring-black/20" />
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Always-visible metadata bar */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-card border-t border-border/50">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-foreground">
              {baseName}
            </h3>
            {totalVariants > 1 && (
              <Badge
                variant="secondary"
                className="shrink-0 text-[10px]"
              >
                {matchingCount < totalVariants
                  ? `${matchingCount}/${totalVariants}`
                  : totalVariants}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate">{author}</p>
        </div>
        {aggregatedTags.length > 0 && (
          <div className="hidden sm:flex flex-wrap gap-1 shrink-0">
            {aggregatedTags.slice(0, 3).map((tag) => (
              <Badge
                key={`${tag.category}:${tag.value}`}
                variant="outline"
                className="text-[10px] text-muted-foreground"
              >
                {tag.value}
              </Badge>
            ))}
            {aggregatedTags.length > 3 && (
              <Badge
                variant="outline"
                className="text-[10px] text-muted-foreground"
              >
                +{aggregatedTags.length - 3}
              </Badge>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** Returns Tailwind grid classes for mosaic. Only 1, 2, or 4 tiles. */
function mosaicGridClasses(count: number): string {
  switch (count) {
    case 1:
      return 'grid-rows-1 grid-cols-1'
    case 2:
      return 'grid-rows-2 grid-cols-1'
    default: // 4
      return 'grid-rows-2 grid-cols-2'
  }
}
