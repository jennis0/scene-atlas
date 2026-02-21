import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { imageApi, getImageUrl, getThumbnailUrl } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Image } from '@/types'

interface ImageViewerProps {
  image: Image
  onClose: () => void
  onNext?: () => void
  onPrevious?: () => void
  onImageChange?: (image: Image) => void
  onEditGroup?: (groupId: number) => void
}

export function ImageViewer({ image, onClose, onNext, onPrevious, onImageChange, onEditGroup }: ImageViewerProps) {
  const { data: variants } = useQuery({
    queryKey: ['variants', image.id],
    queryFn: () => imageApi.getVariants(image.id),
  })

  const hasVariants = variants && variants.length > 1

  // Group variants by sub_variant prefix (e.g. "Snowy / Grid" and "Snowy / No Grid" → group "Snowy")
  // Falls back to ungrouped if no clear pattern
  const variantSections = useMemo(() => {
    if (!variants || variants.length <= 1) return []
    return partitionBySubVariant(variants)
  }, [variants])

  return (
    <div className="fixed inset-0 z-50 bg-black/95" onClick={onClose}>
      <div className="absolute inset-0 flex items-center justify-center p-4">
        {/* Navigation buttons */}
        {onPrevious && (
          <Button
            variant="ghost"
            size="icon"
            className="absolute left-4 top-1/2 -translate-y-1/2 text-white hover:bg-white/20"
            onClick={(e) => {
              e.stopPropagation()
              onPrevious()
            }}
          >
            <ChevronLeft className="h-8 w-8" />
          </Button>
        )}

        {onNext && (
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-4 top-1/2 -translate-y-1/2 text-white hover:bg-white/20"
            onClick={(e) => {
              e.stopPropagation()
              onNext()
            }}
          >
            <ChevronRight className="h-8 w-8" />
          </Button>
        )}

        {/* Top-right controls */}
        <div className="absolute right-4 top-4 flex items-center gap-2 z-10">
          {image.variant_group_id !== null && onEditGroup && (
            <Button
              variant="ghost"
              size="sm"
              className="text-white/80 hover:text-white hover:bg-white/20"
              onClick={(e) => { e.stopPropagation(); onEditGroup(image.variant_group_id!) }}
            >
              Edit Group
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="text-white hover:bg-white/20"
            onClick={onClose}
          >
            <X className="h-6 w-6" />
          </Button>
        </div>

        {/* Image and info — both constrained to the same max height */}
        <div
          className="flex max-w-7xl gap-4 items-stretch"
          style={{ maxHeight: '85vh' }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Main image */}
          <div className="flex-1 flex items-center justify-center min-w-0">
            <img
              src={getImageUrl(image)}
              alt={image.name}
              className="max-h-[85vh] max-w-full object-contain"
            />
          </div>

          {/* Sidebar — constrained to same height as image container */}
          <div className="w-80 shrink-0 flex flex-col bg-background/95 rounded-lg overflow-hidden">
            {/* Fixed header: image metadata */}
            <div className="p-5 pb-4 border-b border-border/50 shrink-0">
              <h2 className="text-xl font-bold truncate">{image.name}</h2>
              <p className="text-sm text-muted-foreground mt-0.5">by {image.author}</p>

              {/* Sub-variant + filename */}
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {image.sub_variant && (
                  <Badge variant="outline" className="text-xs">
                    {image.sub_variant}
                  </Badge>
                )}
                {image.gridded && (
                  <Badge variant="outline" className="text-xs text-muted-foreground">
                    {image.grid_width && image.grid_height
                      ? `Grid ${image.grid_width}×${image.grid_height}`
                      : 'Gridded'}
                  </Badge>
                )}
              </div>

              <p className="mt-1.5 text-[10px] text-muted-foreground/70 truncate" title={image.filename}>
                {image.filename}
              </p>

              {/* Tags */}
              {image.tags && image.tags.length > 0 && (
                <div className="mt-3">
                  <div className="flex flex-wrap gap-1">
                    {image.tags.map((tag) => (
                      <Badge
                        key={tag.id}
                        variant="outline"
                        className="text-[10px] text-muted-foreground"
                      >
                        {tag.category}: {tag.value}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* Colors + Details row */}
              <div className="mt-3 flex items-center gap-3">
                {image.colors && image.colors.length > 0 && (
                  <div className="flex gap-1">
                    {image.colors
                      .sort((a, b) => a.color_order - b.color_order)
                      .map((color) => (
                        <div
                          key={color.id}
                          className="w-5 h-5 rounded border border-border"
                          style={{ backgroundColor: color.color_hex }}
                          title={`${color.color_hex} (${(color.percentage * 100).toFixed(1)}%)`}
                        />
                      ))}
                  </div>
                )}
                <dl className="flex-1 text-[10px] text-muted-foreground flex gap-3">
                  <dd className="text-foreground">{image.width}×{image.height}</dd>
                  <dd className="text-foreground">{(image.file_size / 1024 / 1024).toFixed(1)} MB</dd>
                </dl>
              </div>
            </div>

            {/* Scrollable variants area */}
            {hasVariants && (
              <div className="flex-1 min-h-0 flex flex-col">
                <div className="px-5 pt-3 pb-2 shrink-0">
                  <h3 className="text-sm font-semibold">
                    Variants
                    <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                      ({variants.length})
                    </span>
                  </h3>
                </div>
                <div className="flex-1 overflow-y-auto px-5 pb-4">
                  {variantSections.map((section) => (
                    <div key={section.label} className="mb-3 last:mb-0">
                      {/* Section header — only shown when there are multiple sections */}
                      {variantSections.length > 1 && (
                        <p className="text-[11px] font-medium text-muted-foreground mb-1.5 uppercase tracking-wider">
                          {section.label}
                        </p>
                      )}
                      <div className="grid grid-cols-2 gap-2">
                        {section.images.map((variant) => (
                          <VariantTile
                            key={variant.id}
                            variant={variant}
                            isActive={variant.id === image.id}
                            onClick={() => onImageChange?.(variant)}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

interface VariantSection {
  label: string
  images: Image[]
}

/**
 * Partitions variants by sub_variant value.
 * Each unique sub_variant becomes a section. Variants without sub_variant
 * go into an "Other" section. Returns a single flat section if all
 * sub_variants are null or all identical.
 */
function partitionBySubVariant(variants: Image[]): VariantSection[] {
  const groups = new Map<string, Image[]>()
  const order: string[] = []

  for (const v of variants) {
    const key = v.sub_variant || 'Other'
    if (!groups.has(key)) {
      groups.set(key, [])
      order.push(key)
    }
    groups.get(key)!.push(v)
  }

  // If everything ended up in one section, return it flat (no header needed)
  if (order.length <= 1) {
    return [{ label: order[0] ?? 'All variants', images: variants }]
  }

  return order.map((label) => ({
    label,
    images: groups.get(label)!,
  }))
}

function VariantTile({
  variant,
  isActive,
  onClick,
}: {
  variant: Image
  isActive: boolean
  onClick: () => void
}) {
  const label = filenameStem(variant.filename)

  return (
    <div
      className={`cursor-pointer overflow-hidden rounded-lg border bg-card transition-all duration-200 hover:scale-[1.03] hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5 ${
        isActive ? 'border-primary ring-1 ring-primary/30' : 'border-border'
      }`}
      onClick={onClick}
    >
      <div className="aspect-[4/3] overflow-hidden">
        <img
          src={getThumbnailUrl(variant)}
          alt={label}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      </div>
      <div className="px-2 py-1 bg-card border-t border-border/50">
        <p className="text-[10px] text-muted-foreground truncate" title={variant.filename}>
          {label}
        </p>
        <div className="flex flex-wrap gap-0.5 mt-0.5">
          {variant.gridded && (
            <Badge variant="outline" className="text-[8px] px-1 py-0 text-muted-foreground/60 leading-tight">
              {variant.grid_width && variant.grid_height
                ? `${variant.grid_width}×${variant.grid_height}`
                : 'Grid'}
            </Badge>
          )}
          {variant.tags?.slice(0, 2).map((tag) => (
            <Badge
              key={tag.id}
              variant="outline"
              className="text-[8px] px-1 py-0 text-muted-foreground/60 leading-tight"
            >
              {tag.value}
            </Badge>
          ))}
        </div>
      </div>
    </div>
  )
}

/** Strips extension from a filename for display. */
function filenameStem(filename: string): string {
  return filename.replace(/\.[^.]+$/, '')
}
