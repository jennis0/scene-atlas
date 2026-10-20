import { Pencil, Merge, Layers, FolderDown } from 'lucide-react'
import { getThumbnailUrl, getGroupDownloadUrl } from '@/lib/api'
import { VideoIndicator } from '@/components/ui/video-indicator'
import { CardActionsMenu } from '@/components/CardActionsMenu'
import { DropdownMenuItem } from '@/components/ui/dropdown-menu'
import type { ImageGroup } from '@/types'

interface GroupCardProps {
  group: ImageGroup
  onClick: () => void
  onEdit?: () => void
  onDelete?: () => void
  onMerge?: () => void
}

export function GroupCard({ group, onClick, onEdit, onDelete, onMerge }: GroupCardProps) {
  const { heroImage, mosaicImages, totalScenes, matchingCount, baseName, author, groupId } = group

  const maxMosaic =
    mosaicImages.length >= 4 ? 4 : mosaicImages.length >= 2 ? 2 : mosaicImages.length
  const visibleMosaic = mosaicImages.slice(0, maxMosaic)
  const displayedCount = 1 + visibleMosaic.length
  const overflowCount = totalScenes - displayedCount
  const hasMosaic = visibleMosaic.length > 0

  return (
    <div
      data-testid="group-card"
      className="focus-ring-within group/card relative overflow-hidden rounded-lg border border-border/30 bg-card transition-[transform,box-shadow] duration-200 hover:border-primary/40 hover:shadow-xl hover:shadow-shade/40"
    >
      {/* Covers the whole card: the card's single click and keyboard target. The action
          menu sits above it as a sibling, so neither button is nested in the other. */}
      <button
        type="button"
        aria-label={[baseName, author && `by ${author}`, totalScenes > 1 && `${totalScenes} scenes`]
          .filter(Boolean)
          .join(', ')}
        onClick={onClick}
        className="absolute inset-0 z-[1] cursor-pointer rounded-lg focus-visible:outline-none"
      />

      {groupId !== null && (
        <CardActionsMenu
          label={baseName}
          download={{
            url: getGroupDownloadUrl(groupId),
            filename: `${baseName}.zip`,
            failure: 'Group download failed',
            icon: <FolderDown className="h-4 w-4 mr-2" />,
          }}
          onDelete={onDelete}
        >
          <DropdownMenuItem onClick={() => onEdit?.()}>
            <Pencil className="h-4 w-4 mr-2" />
            Edit
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onMerge?.()}>
            <Merge className="h-4 w-4 mr-2" />
            Merge into...
          </DropdownMenuItem>
        </CardActionsMenu>
      )}

      <div className="flex" style={{ height: '160px' }}>
        <div
          className="transparency-backdrop relative h-full shrink-0 overflow-hidden"
          style={{ width: hasMosaic ? '60%' : '100%' }}
        >
          <img
            src={getThumbnailUrl(heroImage)}
            alt=""
            width={240}
            height={160}
            decoding="async"
            className="h-full w-full object-cover"
            loading="lazy"
          />
          {heroImage.media_type === 'video' && <VideoIndicator />}
          {hasMosaic && <div className="absolute inset-y-0 right-0 w-px bg-black/30" />}
        </div>

        {hasMosaic && (
          <div className="relative h-full shrink-0 overflow-hidden" style={{ width: '40%' }}>
            <div className={`grid h-full ${mosaicGridClasses(visibleMosaic.length)}`}>
              {visibleMosaic.map((img, i) => {
                const isOverflowTile = i === visibleMosaic.length - 1 && overflowCount > 0
                return (
                  <div key={img.id} className="transparency-backdrop relative overflow-hidden">
                    <img
                      src={getThumbnailUrl(img)}
                      alt=""
                      width={96}
                      height={80}
                      decoding="async"
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                    {img.media_type === 'video' && !isOverflowTile && <VideoIndicator size="sm" />}
                    {img.subgroup && !isOverflowTile && (
                      <div className="caption-band absolute bottom-0 left-0 right-0 px-1.5 py-0.5">
                        <span className="text-3xs leading-tight text-white/90 hc:text-white line-clamp-1">
                          {img.subgroup}
                        </span>
                      </div>
                    )}
                    {isOverflowTile && (
                      <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/60 backdrop-blur-[2px]">
                        <span className="text-lg font-bold text-white">+{overflowCount}</span>
                        <span className="text-2xs text-white/90 hc:text-white">more</span>
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

      {/* Gradient overlay — full width for visual continuity, text constrained to hero area */}
      <div
        aria-hidden="true"
        className="caption-scrim [--scrim-fade:2.5rem] absolute inset-x-0 bottom-0 pb-2.5 px-3 pointer-events-none"
      >
        <div style={{ maxWidth: hasMosaic ? '60%' : '100%' }}>
          <p className="text-xs font-medium text-white leading-snug line-clamp-1 drop-shadow truncate">
            {baseName}
          </p>
          {author && (
            <p className="text-2xs text-white/85 hc:text-white truncate mt-0.5">{author}</p>
          )}
          {totalScenes > 1 && (
            <div className="flex items-center gap-1 mt-0.5">
              <Layers className="h-3 w-3 text-white/70 hc:text-white" />
              <span className="text-2xs tabular-nums text-white/85 hc:text-white">
                {matchingCount < totalScenes
                  ? `${matchingCount} of ${totalScenes} scenes`
                  : `${totalScenes} scenes`}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function mosaicGridClasses(count: number): string {
  switch (count) {
    case 1:
      return 'grid-rows-1 grid-cols-1'
    case 2:
      return 'grid-rows-2 grid-cols-1'
    default:
      return 'grid-rows-2 grid-cols-2'
  }
}
