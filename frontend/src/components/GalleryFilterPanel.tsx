import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { FilterMenuContent, type FilterOptionGroup } from '@/components/FilterMenuContent'
import type { ActiveFilter } from '@/components/import/fileFilter'
import type { FacetData } from '@/types'
import { COLOR_FILTER_PALETTE } from '@/lib/colorPalette'
import { tagApi } from '@/lib/api'
import { parseTagVocabulary } from '@/components/import/types'

interface GalleryFilterPanelProps {
  filters: ActiveFilter[]
  facets: FacetData | undefined
  onFiltersChange: (filters: ActiveFilter[]) => void
}

export function GalleryFilterPanel({ filters, facets, onFiltersChange }: GalleryFilterPanelProps) {
  const [open, setOpen] = useState(false)

  // Re-uses the cached tagCategories query — no extra network request
  const { data: tagCategories } = useQuery({
    queryKey: ['tagCategories'],
    queryFn: tagApi.getCategories,
    staleTime: 30_000,
  })
  const tagVocab = useMemo(
    () => (tagCategories ? parseTagVocabulary(tagCategories) : []),
    [tagCategories],
  )

  const groups: FilterOptionGroup[] = []

  const authors = facets?.authors ?? []
  if (authors.length > 0) {
    groups.push({
      id: 'author',
      label: 'Author',
      type: 'author',
      options: authors.map((a) => ({
        filterValue: a.value,
        label: a.value,
        filterLabel: `author: ${a.value}`,
        count: a.count,
      })),
    })
  }

  const gridded = facets?.gridded
  if (gridded) {
    groups.push({
      id: 'gridded',
      label: 'Grid',
      type: 'gridded',
      options: [
        {
          filterValue: 'square',
          label: 'Square grid',
          filterLabel: 'grid: Square',
          count: gridded.square,
        },
        {
          filterValue: 'hex',
          label: 'Hex grid',
          filterLabel: 'grid: Hex',
          count: gridded.hex,
        },
        {
          filterValue: 'gridded',
          label: 'Any gridded',
          filterLabel: 'grid: Gridded',
          count: gridded.gridded,
        },
        {
          filterValue: 'gridless',
          label: 'Gridless',
          filterLabel: 'grid: Gridless',
          count: gridded.gridless,
        },
        {
          filterValue: 'unknown',
          label: 'Unknown',
          filterLabel: 'grid: Unknown',
          count: gridded.unknown,
        },
      ].filter((o) => o.count > 0),
    })
  }

  const mediaTypes = facets?.media_types ?? []
  if (mediaTypes.length > 1) {
    groups.push({
      id: 'media_type',
      label: 'Media',
      type: 'media_type',
      options: mediaTypes.map((m) => ({
        filterValue: m.value,
        label: m.value === 'image' ? 'Images' : m.value === 'video' ? 'Videos' : m.value,
        filterLabel: `media: ${m.value === 'image' ? 'Images' : m.value === 'video' ? 'Videos' : m.value}`,
        count: m.count,
      })),
    })
  }

  groups.push({
    id: 'color',
    label: 'Color',
    type: 'color',
    options: COLOR_FILTER_PALETTE.map((c) => ({
      filterValue: c.hex,
      label: c.label,
      filterLabel: c.label,
    })),
  })

  for (const [cat, values] of Object.entries(facets?.tags ?? {})) {
    if (values.length === 0) continue
    const vocabEntry = tagVocab.find((v) => v.category === cat)
    groups.push({
      id: cat,
      label: cat,
      type: 'tag',
      options: values.map((v) => ({
        filterValue: `${cat}:${v.value}`,
        label: v.value,
        filterLabel: `${cat}: ${v.value}`,
        count: v.count,
        aliases: vocabEntry?.aliases[v.value],
      })),
    })
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={`h-10 gap-2 flex-shrink-0 text-sm ${filters.length > 0 ? 'border-primary/60 text-primary' : 'text-muted-foreground hover:text-foreground'}`}
          title="Filters"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          Filters
          {filters.length > 0 && (
            <span className="h-4 min-w-4 px-1 rounded-full bg-primary text-[10px] font-bold text-primary-foreground flex items-center justify-center tabular-nums">
              {filters.length}
            </span>
          )}
        </Button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        className="w-[400px] p-0 h-[520px] flex flex-col bg-card rounded-lg overflow-hidden"
      >
        {groups.length > 0 ? (
          <FilterMenuContent
            groups={groups}
            activeFilters={filters}
            onFiltersChange={onFiltersChange}
          />
        ) : (
          <p className="px-3 py-6 text-xs text-muted-foreground text-center">
            No filters available
          </p>
        )}
      </PopoverContent>
    </Popover>
  )
}
