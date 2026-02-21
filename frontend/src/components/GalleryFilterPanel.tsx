import { useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { FilterMenuContent, type FilterOptionGroup } from '@/components/FilterMenuContent'
import type { ActiveFilter } from '@/components/import/fileFilter'
import type { FacetData } from '@/types'

interface GalleryFilterPanelProps {
  filters: ActiveFilter[]
  facets: FacetData | undefined
  onFiltersChange: (filters: ActiveFilter[]) => void
}

export function GalleryFilterPanel({ filters, facets, onFiltersChange }: GalleryFilterPanelProps) {
  const [open, setOpen] = useState(false)

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
      label: 'Grid state',
      type: 'gridded',
      options: [
        { filterValue: 'gridded',  label: 'Gridded',  filterLabel: 'grid: Gridded',  count: gridded.gridded },
        { filterValue: 'gridless', label: 'Gridless', filterLabel: 'grid: Gridless', count: gridded.gridless },
        { filterValue: 'unknown',  label: 'Unknown',  filterLabel: 'grid: Unknown',  count: gridded.unknown },
      ].filter((o) => o.count > 0),
    })
  }

  for (const [cat, values] of Object.entries(facets?.tags ?? {})) {
    if (values.length === 0) continue
    groups.push({
      id: cat,
      label: cat,
      type: 'tag',
      options: values.map((v) => ({
        filterValue: `${cat}:${v.value}`,
        label: v.value,
        filterLabel: `${cat}: ${v.value}`,
        count: v.count,
      })),
    })
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          className={`relative flex-shrink-0 ${filters.length > 0 ? 'border-emerald-400 text-emerald-600' : ''}`}
          title="Filters"
        >
          <SlidersHorizontal className="h-4 w-4" />
          {filters.length > 0 && (
            <span className="absolute -top-1.5 -right-1.5 h-4 w-4 rounded-full bg-emerald-500 text-[10px] font-bold text-white flex items-center justify-center">
              {filters.length}
            </span>
          )}
        </Button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-[400px] p-0 h-[420px] flex flex-col">
        {groups.length > 0 ? (
          <FilterMenuContent
            groups={groups}
            activeFilters={filters}
            onFiltersChange={onFiltersChange}
          />
        ) : (
          <p className="px-3 py-6 text-xs text-slate-400 text-center">No filters available</p>
        )}
      </PopoverContent>
    </Popover>
  )
}
