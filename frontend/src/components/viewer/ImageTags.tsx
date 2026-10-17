import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { tagApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
import { TagChip } from '@/components/TagChip'
import { TagPicker } from '@/components/import/TagPicker'
import { parseTagVocabulary } from '@/components/import/types'
import type { Image, TagData } from '@/types'

interface ImageTagsProps {
  image: Image
  onAddTag: (tag: TagData) => void
  onRemoveTag: (tagId: number) => void
  removing: boolean
}

/** Dominant colours, tag chips and the tag picker. */
export function ImageTags({ image, onAddTag, onRemoveTag, removing }: ImageTagsProps) {
  const { data: tagCategories } = useQuery({
    queryKey: QUERY_KEYS.tagCategories,
    queryFn: () => tagApi.getCategories(),
    staleTime: 5 * 60_000,
  })

  // From the full category list rather than facets, so vocabulary values that no
  // image has yet are still offered.
  const vocab = useMemo(
    () => (tagCategories ? parseTagVocabulary(tagCategories) : []),
    [tagCategories],
  )

  const existingTags = useMemo(
    (): TagData[] =>
      (image.tags ?? []).map((t) => ({
        category: t.category,
        value: t.value,
        confidence: t.confidence,
        source: t.source,
      })),
    [image.tags],
  )

  return (
    <div className="border-t border-border/30 pt-3 mt-1 short:flex short:items-start short:gap-3">
      {image.colors && image.colors.length > 0 && (
        <div className="flex gap-1 mb-2 shrink-0 short:mb-0 short:pt-0.5">
          {[...image.colors]
            .sort((a, b) => a.color_order - b.color_order)
            .map((color) => (
              <div
                key={color.id}
                className="h-5 w-5 rounded-full ring-1 ring-foreground/15 shadow-sm"
                style={{ backgroundColor: color.color_hex }}
                title={`${color.color_hex} (${(color.percentage * 100).toFixed(1)}%)`}
              />
            ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5 short:flex-1">
        {image.tags?.map((tag) => (
          <TagChip
            key={tag.id}
            category={tag.category}
            value={tag.value}
            onRemove={() => onRemoveTag(tag.id)}
            removeDisabled={removing}
          />
        ))}

        <TagPicker vocab={vocab} existingTags={existingTags} onAdd={onAddTag} />
      </div>
    </div>
  )
}
