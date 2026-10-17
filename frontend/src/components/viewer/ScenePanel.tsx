import { useState } from 'react'
import { Search, SlidersHorizontal, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SceneTile } from '@/components/SceneTile'
import { FilterMenuContent, FilterChipList } from '@/components/FilterMenuContent'
import type { ImageTypeFilter } from '@/components/import/fileFilter'
import type { useSceneFilters } from '@/hooks/useSceneFilters'
import type { Image } from '@/types'

const TYPE_OPTIONS: readonly (readonly [string, ImageTypeFilter])[] = [
  ['All', 'all'],
  ['Maps', 'battlemap'],
  ['Scenes', 'scene'],
]

interface ScenePanelProps {
  scenes: Image[]
  sceneFilters: ReturnType<typeof useSceneFilters>
  activeImageId: number
  onSceneClick: (scene: Image) => void
  scrollRef: React.RefObject<HTMLDivElement>
}

function gridLabel(scene: Image): string | undefined {
  if (!scene.gridded || scene.image_type === 'scene') return undefined
  return scene.grid_width && scene.grid_height ? `${scene.grid_width}×${scene.grid_height}` : 'Grid'
}

/** The viewer's scrolling list of the other images in the group, with its filter bar. */
export function ScenePanel({
  scenes,
  sceneFilters,
  activeImageId,
  onSceneClick,
  scrollRef,
}: ScenePanelProps) {
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const { filter, setFilter, filterGroups, hasMixedTypes, filtered, sections } = sceneFilters
  const setActive = (active: typeof filter.active) => setFilter((f) => ({ ...f, active }))

  const hasSearch = !!filter.text || filter.imageType !== 'all'
  const hasActiveFilters = filter.active.length > 0
  // Whether there is anything to filter on, not whether a filter is applied
  const hasFilterableData = filterGroups.length > 0

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
      <div className="sticky top-0 z-10 bg-card border-b border-border/30">
        <div className="px-4 py-2 flex items-center gap-2">
          <span className="text-sm font-semibold shrink-0">
            Scenes
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              ({filtered.length}
              {hasSearch || hasActiveFilters ? `/${scenes.length}` : ''})
            </span>
          </span>

          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
            <Input
              inputSize="sm"
              value={filter.text}
              onChange={(e) => {
                const text = e.target.value
                setFilter((f) => ({ ...f, text }))
              }}
              placeholder="Filter…"
              className={`pl-6 ${hasSearch ? 'pr-6' : 'pr-2'}`}
            />
            {hasSearch && (
              <button
                onClick={() => setFilter((f) => ({ ...f, text: '', imageType: 'all' }))}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground/40 hover:text-muted-foreground transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          {hasMixedTypes && (
            <div className="inline-flex rounded border border-border overflow-hidden shrink-0">
              {TYPE_OPTIONS.map(([label, val]) => (
                <button
                  key={val}
                  onClick={() => setFilter((f) => ({ ...f, imageType: val }))}
                  className={`px-1.5 py-0.5 text-[10px] transition-colors ${
                    filter.imageType === val
                      ? 'bg-primary/20 text-primary font-medium'
                      : 'text-muted-foreground/60 hover:text-muted-foreground hover:bg-secondary/50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {/* Always present; greyed when there is nothing to filter on */}
          <Popover
            open={hasFilterableData ? filterPopoverOpen : false}
            onOpenChange={hasFilterableData ? setFilterPopoverOpen : undefined}
          >
            <PopoverTrigger asChild>
              <button
                disabled={!hasFilterableData}
                className={`relative h-6 w-6 rounded flex items-center justify-center shrink-0 transition-colors ${
                  hasActiveFilters
                    ? 'bg-primary/20 text-primary border border-primary/40'
                    : hasFilterableData
                      ? 'text-muted-foreground hover:text-foreground hover:bg-secondary border border-transparent'
                      : 'text-muted-foreground/25 border border-transparent cursor-not-allowed'
                }`}
                title={hasFilterableData ? 'Filter scenes' : 'No filterable dimensions'}
              >
                <SlidersHorizontal className="h-3 w-3" />
                {hasActiveFilters && (
                  <span className="absolute -top-1 -right-1 h-4 min-w-4 px-1 rounded-full bg-primary text-[10px] font-bold text-primary-foreground flex items-center justify-center tabular-nums">
                    {filter.active.length}
                  </span>
                )}
              </button>
            </PopoverTrigger>
            {hasFilterableData && (
              <PopoverContent
                align="end"
                side="left"
                className="w-[400px] p-0 h-[480px] flex flex-col"
              >
                <FilterMenuContent
                  groups={filterGroups}
                  activeFilters={filter.active}
                  onFiltersChange={setActive}
                />
              </PopoverContent>
            )}
          </Popover>
        </div>

        {hasActiveFilters && (
          <div className="px-4 pb-2">
            <FilterChipList filters={filter.active} onFiltersChange={setActive} />
          </div>
        )}
      </div>

      <div className="px-4 pt-3 pb-4">
        {filtered.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-6">No scenes match</p>
        ) : (
          sections.map((section) => (
            <div key={section.label} className="mb-3 last:mb-0">
              {sections.length > 1 && (
                <p className="text-[11px] font-medium text-muted-foreground mb-2 uppercase tracking-wider">
                  {section.label}
                </p>
              )}
              <div className="grid grid-cols-2 gap-2">
                {section.images.map((scene) => (
                  <SceneTile
                    key={scene.id}
                    image={scene}
                    isActive={scene.id === activeImageId}
                    primaryText={scene.name}
                    secondaryText={gridLabel(scene)}
                    onClick={() => onSceneClick(scene)}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
