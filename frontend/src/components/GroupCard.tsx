import { getThumbnailUrl } from '@/lib/api'
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
  } = group

  const maxMosaic = mosaicImages.length >= 4 ? 4 : mosaicImages.length >= 2 ? 2 : mosaicImages.length
  const visibleMosaic = mosaicImages.slice(0, maxMosaic)
  const displayedCount = 1 + visibleMosaic.length
  const overflowCount = totalVariants - displayedCount
  const hasMosaic = visibleMosaic.length > 0

  return (
    <div
      className="group/card relative cursor-pointer overflow-hidden rounded-lg border border-border/30 bg-card transition-all duration-200 hover:border-primary/40 hover:shadow-xl hover:shadow-black/40"
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
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]"
            loading="lazy"
          />
          {hasMosaic && <div className="absolute inset-y-0 right-0 w-px bg-black/30" />}
        </div>

        {/* Mosaic grid */}
        {hasMosaic && (
          <div className="relative h-full shrink-0 overflow-hidden" style={{ width: '40%' }}>
            <div className={`grid h-full ${mosaicGridClasses(visibleMosaic.length)}`}>
              {visibleMosaic.map((img, i) => {
                const isOverflowTile = i === visibleMosaic.length - 1 && overflowCount > 0
                return (
                  <div key={img.id} className="relative overflow-hidden">
                    <img
                      src={getThumbnailUrl(img)}
                      alt={img.sub_variant || img.name}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                    {img.sub_variant && !isOverflowTile && (
                      <div className="absolute bottom-0 left-0 right-0 bg-black/50 px-1.5 py-0.5">
                        <span className="text-[10px] leading-tight text-white/90 line-clamp-1">
                          {img.sub_variant}
                        </span>
                      </div>
                    )}
                    {isOverflowTile && (
                      <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/60 backdrop-blur-[2px]">
                        <span className="text-lg font-bold text-white">+{overflowCount}</span>
                        <span className="text-[10px] text-white/70">more</span>
                      </div>
                    )}
                    <div className="absolute inset-0 pointer-events-none ring-[0.5px] ring-inset ring-black/20" />
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Gradient overlay — name + variant count + author */}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/55 to-transparent pt-10 pb-2.5 px-3 pointer-events-none">
        <div className="flex items-center gap-2">
          <p className="text-[13px] font-medium text-white leading-snug line-clamp-1 drop-shadow flex-1 truncate">
            {baseName}
          </p>
          {totalVariants > 1 && (
            <span className="shrink-0 tabular-nums text-[11px] bg-black/50 text-white/75 px-1.5 py-px rounded-full border border-white/10">
              {matchingCount < totalVariants ? `${matchingCount}/${totalVariants}` : totalVariants}
            </span>
          )}
        </div>
        <p className="text-[11px] text-white/60 truncate mt-0.5">{author}</p>
      </div>
    </div>
  )
}

function mosaicGridClasses(count: number): string {
  switch (count) {
    case 1: return 'grid-rows-1 grid-cols-1'
    case 2: return 'grid-rows-2 grid-cols-1'
    default: return 'grid-rows-2 grid-cols-2'
  }
}
