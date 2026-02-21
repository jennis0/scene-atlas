import { useState } from 'react'
import { SlidersHorizontal, X, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { ActiveFilter } from '@/components/import/fileFilter'
import type { FacetData } from '@/types'

interface GalleryFilterPanelProps {
  filters: ActiveFilter[]
  facets: FacetData | undefined
  onFiltersChange: (filters: ActiveFilter[]) => void
}

export function GalleryFilterPanel({ filters, facets, onFiltersChange }: GalleryFilterPanelProps) {
  const [open, setOpen] = useState(false)
  const [optionSearch, setOptionSearch] = useState('')

  const addFilter = (af: ActiveFilter) => {
    if (filters.some((f) => f.type === af.type && f.value === af.value && f.exclude === af.exclude)) return
    onFiltersChange([...filters, af])
    setOpen(false)
  }

  const removeFilter = (i: number) => {
    onFiltersChange(filters.filter((_, j) => j !== i))
  }

  const toggleFilterMode = (i: number) => {
    onFiltersChange(filters.map((f, j) => (j === i ? { ...f, exclude: !f.exclude } : f)))
  }

  const search = optionSearch.toLowerCase()

  // Filter authors by search text
  const visibleAuthors = (facets?.authors ?? []).filter(
    (a) => !search || a.value.toLowerCase().includes(search)
  )

  // Filter tags by search text
  const visibleTags: Record<string, { value: string; count: number }[]> = {}
  for (const [cat, values] of Object.entries(facets?.tags ?? {})) {
    const filtered = values.filter(
      (v) => !search || cat.toLowerCase().includes(search) || v.value.toLowerCase().includes(search)
    )
    if (filtered.length > 0) visibleTags[cat] = filtered
  }

  // Grid states
  const gridStates: { value: string; label: string; count: number }[] = [
    { value: 'gridded', label: 'Gridded', count: facets?.gridded.gridded ?? 0 },
    { value: 'gridless', label: 'Gridless', count: facets?.gridded.gridless ?? 0 },
    { value: 'unknown', label: 'Unknown', count: facets?.gridded.unknown ?? 0 },
  ].filter((gs) => !search || gs.label.toLowerCase().includes(search))

  const hasAnyOptions =
    visibleAuthors.length > 0 ||
    Object.keys(visibleTags).length > 0 ||
    gridStates.length > 0

  return (
    <div className="flex flex-col gap-0">
      {/* Funnel button */}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="icon"
            className={`relative ${filters.length > 0 ? 'border-emerald-400 text-emerald-600' : ''}`}
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

        <PopoverContent align="end" className="w-72 p-0 max-h-[480px] flex flex-col">
          {/* Search within popover */}
          <div className="p-2 border-b border-slate-100 flex-shrink-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-300 pointer-events-none" />
              <input
                value={optionSearch}
                onChange={(e) => setOptionSearch(e.target.value)}
                placeholder="Search filters…"
                className="w-full h-7 pl-8 pr-7 text-sm bg-slate-50 border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-emerald-300 focus:border-emerald-300 text-slate-600 placeholder:text-slate-300"
              />
              {optionSearch && (
                <button
                  onClick={() => setOptionSearch('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-300 hover:text-slate-500"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>

          <div className="overflow-y-auto flex-1">
            {!hasAnyOptions && (
              <p className="px-3 py-6 text-xs text-slate-400 text-center">
                {optionSearch ? `No filters match "${optionSearch}"` : 'No filters available'}
              </p>
            )}

            {/* Authors */}
            {visibleAuthors.length > 0 && (
              <FilterSection label="Author">
                {visibleAuthors.map((a) => (
                  <FilterOptionRow
                    key={`author-${a.value}`}
                    label={a.value}
                    count={a.count}
                    onInclude={() => addFilter({ type: 'author', value: a.value, label: `author: ${a.value}`, exclude: false })}
                    onExclude={() => addFilter({ type: 'author', value: a.value, label: `author: ${a.value}`, exclude: true })}
                  />
                ))}
              </FilterSection>
            )}

            {/* Grid state */}
            {gridStates.length > 0 && (
              <FilterSection label="Grid state">
                {gridStates.map((gs) => (
                  <FilterOptionRow
                    key={`grid-${gs.value}`}
                    label={gs.label}
                    count={gs.count}
                    onInclude={() => addFilter({ type: 'gridded', value: gs.value, label: `grid: ${gs.label}`, exclude: false })}
                    onExclude={() => addFilter({ type: 'gridded', value: gs.value, label: `grid: ${gs.label}`, exclude: true })}
                  />
                ))}
              </FilterSection>
            )}

            {/* Tags by category */}
            {Object.entries(visibleTags).map(([cat, values]) => (
              <FilterSection key={cat} label={cat}>
                {values.map((v) => (
                  <FilterOptionRow
                    key={`tag-${cat}-${v.value}`}
                    label={v.value}
                    count={v.count}
                    onInclude={() => addFilter({ type: 'tag', value: `${cat}:${v.value}`, label: `${cat}: ${v.value}`, exclude: false })}
                    onExclude={() => addFilter({ type: 'tag', value: `${cat}:${v.value}`, label: `${cat}: ${v.value}`, exclude: true })}
                  />
                ))}
              </FilterSection>
            ))}
          </div>
        </PopoverContent>
      </Popover>

      {/* Active filter chips — rendered outside the popover, below the search bar row */}
      {filters.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-2">
          {filters.map((af, i) => (
            <span
              key={i}
              className={`inline-flex items-center gap-1 text-xs rounded-full border px-2 py-0.5
                ${af.exclude
                  ? 'border-red-200 bg-red-50 text-red-600'
                  : 'border-emerald-200 bg-emerald-50 text-emerald-700'
                }`}
            >
              <span className="capitalize">{af.label}</span>
              <button
                onClick={() => toggleFilterMode(i)}
                className="opacity-60 hover:opacity-100 text-[10px] font-medium transition-opacity"
                title="Toggle include/exclude"
              >
                {af.exclude ? 'hide' : 'only'}
              </button>
              <button
                onClick={() => removeFilter(i)}
                className="hover:opacity-80 transition-opacity ml-0.5"
                title="Remove filter"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
          {filters.length > 1 && (
            <button
              onClick={() => onFiltersChange([])}
              className="text-xs text-slate-400 hover:text-slate-600 px-1 transition-colors"
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function FilterSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider capitalize">
        {label}
      </div>
      {children}
    </div>
  )
}

function FilterOptionRow({
  label,
  count,
  onInclude,
  onExclude,
}: {
  label: string
  count: number
  onInclude: () => void
  onExclude: () => void
}) {
  return (
    <div className="flex items-center justify-between px-3 py-1 hover:bg-slate-50">
      <div className="flex items-center gap-1.5 flex-1 min-w-0 mr-2">
        <span className="text-sm text-slate-700 capitalize truncate">{label}</span>
        <span className="text-[10px] text-slate-400 tabular-nums flex-shrink-0">{count}</span>
      </div>
      <div className="flex gap-1 flex-shrink-0">
        <button
          onClick={onInclude}
          className="text-[11px] px-1.5 py-0.5 rounded text-emerald-600 hover:bg-emerald-50 font-medium transition-colors"
        >
          Only
        </button>
        <button
          onClick={onExclude}
          className="text-[11px] px-1.5 py-0.5 rounded text-red-500 hover:bg-red-50 font-medium transition-colors"
        >
          Hide
        </button>
      </div>
    </div>
  )
}
