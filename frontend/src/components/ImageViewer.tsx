import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { imageApi, getImageUrl } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Image } from '@/types'

interface ImageViewerProps {
  image: Image
  onClose: () => void
  onNext?: () => void
  onPrevious?: () => void
}

export function ImageViewer({ image, onClose, onNext, onPrevious }: ImageViewerProps) {
  const { data: variants } = useQuery({
    queryKey: ['variants', image.id],
    queryFn: () => imageApi.getVariants(image.id),
  })

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

        {/* Close button */}
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-4 top-4 text-white hover:bg-white/20"
          onClick={onClose}
        >
          <X className="h-6 w-6" />
        </Button>

        {/* Image and info */}
        <div className="flex max-h-full max-w-7xl gap-4" onClick={(e) => e.stopPropagation()}>
          {/* Main image */}
          <div className="flex-1 flex items-center justify-center">
            <img
              src={getImageUrl(image)}
              alt={image.name}
              className="max-h-[90vh] max-w-full object-contain"
            />
          </div>

          {/* Sidebar with info */}
          <div className="w-80 overflow-y-auto bg-background/95 p-6 rounded-lg">
            <h2 className="text-2xl font-bold mb-2">{image.name}</h2>
            <p className="text-sm text-muted-foreground mb-4">by {image.author}</p>

            {/* Tags */}
            {image.tags && image.tags.length > 0 && (
              <div className="mb-4">
                <h3 className="text-sm font-semibold mb-2">Tags</h3>
                <div className="flex flex-wrap gap-1">
                  {image.tags.map((tag) => (
                    <Badge key={tag.id} variant="secondary">
                      {tag.category}: {tag.value}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Colors */}
            {image.colors && image.colors.length > 0 && (
              <div className="mb-4">
                <h3 className="text-sm font-semibold mb-2">Dominant Colors</h3>
                <div className="flex gap-2">
                  {image.colors
                    .sort((a, b) => a.color_order - b.color_order)
                    .map((color) => (
                      <div
                        key={color.id}
                        className="w-8 h-8 rounded border border-border"
                        style={{ backgroundColor: color.color_hex }}
                        title={`${color.color_hex} (${(color.percentage * 100).toFixed(1)}%)`}
                      />
                    ))}
                </div>
              </div>
            )}

            {/* Dimensions */}
            <div className="mb-4">
              <h3 className="text-sm font-semibold mb-2">Details</h3>
              <dl className="text-sm space-y-1">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Dimensions:</dt>
                  <dd>{image.width} × {image.height}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">File size:</dt>
                  <dd>{(image.file_size / 1024 / 1024).toFixed(2)} MB</dd>
                </div>
              </dl>
            </div>

            {/* Variants */}
            {variants && variants.length > 1 && (
              <div>
                <h3 className="text-sm font-semibold mb-2">
                  Variants ({variants.length})
                </h3>
                <div className="grid grid-cols-2 gap-2">
                  {variants.map((variant) => (
                    <div
                      key={variant.id}
                      className={`cursor-pointer rounded border-2 ${
                        variant.id === image.id
                          ? 'border-primary'
                          : 'border-transparent hover:border-muted'
                      }`}
                    >
                      <img
                        src={getImageUrl(variant)}
                        alt={variant.name}
                        className="w-full h-20 object-cover rounded"
                      />
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
