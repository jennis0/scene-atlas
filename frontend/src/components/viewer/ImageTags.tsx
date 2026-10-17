import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { tagApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
import { useGetTagColor } from '@/contexts/TagColorContext'
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
  const getTagColor = useGetTagColor()

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
    <div className="border-t border-border/30 pt-3 mt-1">
      {image.colors && image.colors.length > 0 && (
        <div className="flex gap-1 mb-2">
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

      <div className="flex flex-wrap gap-1.5">
        {image.tags?.map((tag) => {
          const colors = getTagColor(tag.category)
          return (
            <span
              key={tag.id}
              title={tag.category}
              className={`inline-flex items-center gap-1 text-[11px] rounded-full border px-2 py-px ${colors.bg} ${colors.text} ${colors.border}`}
            >
              <span className="capitalize">{tag.value}</span>
              <button
                onClick={() => onRemoveTag(tag.id)}
                disabled={removing}
                className="opacity-40 hover:opacity-100 transition-opacity ml-0.5 disabled:cursor-not-allowed"
                title={`Remove ${tag.category}: ${tag.value}`}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          )
        })}

        <TagPicker vocab={vocab} existingTags={existingTags} onAdd={onAddTag} />
      </div>
    </div>
  )
}
