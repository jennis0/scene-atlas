import { useState } from 'react'
import { MoreHorizontal, Pencil, Merge, Trash2, Layers, FolderDown } from 'lucide-react'
import { getThumbnailUrl, getGroupDownloadUrl } from '@/lib/api'
import { VideoIndicator } from '@/components/ui/video-indicator'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
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
  const [downloading, setDownloading] = useState(false)

  const maxMosaic =
    mosaicImages.length >= 4 ? 4 : mosaicImages.length >= 2 ? 2 : mosaicImages.length
  const visibleMosaic = mosaicImages.slice(0, maxMosaic)
  const displayedCount = 1 + visibleMosaic.length
  const overflowCount = totalScenes - displayedCount
  const hasMosaic = visibleMosaic.length > 0
  const hasActions = groupId !== null

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!groupId || downloading) return
    setDownloading(true)
    try {
      const resp = await fetch(getGroupDownloadUrl(groupId))
      const blob = await resp.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = `${baseName}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      console.error('Group download failed', err)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div
      data-testid="group-card"
      className="group/card relative cursor-pointer overflow-hidden rounded-lg border border-border/30 bg-card transition-[transform,box-shadow] duration-200 hover:border-primary/40 hover:shadow-xl hover:shadow-black/40"
      onClick={onClick}
    >
      {/* Action menu — top-right, visible on hover */}
      {hasActions && (
        <div className="absolute top-2 right-2 z-10">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="opacity-0 group-hover/card:opacity-100 h-7 w-7 rounded-md flex items-center justify-center bg-black/50 text-white/80 hover:text-white hover:bg-black/70 backdrop-blur-sm transition-all"
                onClick={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              onClick={(e) => e.stopPropagation()}
              onCloseAutoFocus={(e) => e.preventDefault()}
            >
              <DropdownMenuItem onClick={() => onEdit?.()}>
                <Pencil className="h-4 w-4 mr-2" />
                Edit
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onMerge?.()}>
                <Merge className="h-4 w-4 mr-2" />
                Merge into...
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleDownload} disabled={downloading}>
                <FolderDown className="h-4 w-4 mr-2" />
                {downloading ? 'Downloading…' : 'Download'}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onDelete?.()}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

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
            width={240}
            height={160}
            decoding="async"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]"
            loading="lazy"
          />
          {heroImage.media_type === 'video' && <VideoIndicator />}
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
                      alt={img.subgroup || img.name}
                      width={96}
                      height={80}
                      decoding="async"
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                    {img.media_type === 'video' && !isOverflowTile && <VideoIndicator size="sm" />}
                    {img.subgroup && !isOverflowTile && (
                      <div className="absolute bottom-0 left-0 right-0 bg-black/50 px-1.5 py-0.5">
                        <span className="text-[10px] leading-tight text-white/90 line-clamp-1">
                          {img.subgroup}
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

      {/* Gradient overlay — full width for visual continuity, text constrained to hero area */}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/55 to-transparent pt-10 pb-2.5 px-3 pointer-events-none">
        <div style={{ maxWidth: hasMosaic ? '60%' : '100%' }}>
          <p className="text-[13px] font-medium text-white leading-snug line-clamp-1 drop-shadow truncate">
            {baseName}
          </p>
          {author && <p className="text-[11px] text-white/60 truncate mt-0.5">{author}</p>}
          {totalScenes > 1 && (
            <div className="flex items-center gap-1 mt-0.5">
              <Layers className="h-3 w-3 text-white/40" />
              <span className="text-[11px] tabular-nums text-white/50">
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
