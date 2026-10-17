import { useState } from 'react'
import { Search, SlidersHorizontal, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SceneTile } from '@/components/SceneTile'
import { FilterMenuContent, FilterChipList } from '@/components/FilterMenuContent'
import type { FileFilter, ImageTypeFilter } from '@/components/import/fileFilter'
import type { SceneSection, useSceneFilters } from '@/hooks/useSceneFilters'
import type { Image } from '@/types'

type SceneFilters = ReturnType<typeof useSceneFilters>
type SetFilter = SceneFilters['setFilter']

const TYPE_OPTIONS: readonly (readonly [string, ImageTypeFilter])[] = [
  ['All', 'all'],
  ['Maps', 'battlemap'],
  ['Scenes', 'scene'],
]

interface ScenePanelProps {
  scenes: Image[]
  sceneFilters: SceneFilters
  activeImageId: number
  onSceneClick: (scene: Image) => void
  scrollRef: React.RefObject<HTMLDivElement>
}

/** The viewer's scrolling list of the other images in the group, with its filter bar. */
export function ScenePanel({
  scenes,
  sceneFilters,
  activeImageId,
  onSceneClick,
  scrollRef,
}: ScenePanelProps) {
  const { filter, setFilter, filtered, sections } = sceneFilters
  const setActive = (active: FileFilter['active']) => setFilter((f) => ({ ...f, active }))
  const isFiltered = !!filter.text || filter.imageType !== 'all' || filter.active.length > 0

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
      <div className="sticky top-0 z-10 bg-card border-b border-border/30">
        <div className="px-4 py-2 flex items-center gap-2">
          <span className="text-sm font-semibold shrink-0">
            Scenes
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              ({filtered.length}
              {isFiltered ? `/${scenes.length}` : ''})
            </span>
          </span>
          <SearchBox filter={filter} setFilter={setFilter} />
          {sceneFilters.hasMixedTypes && <TypeToggle filter={filter} setFilter={setFilter} />}
          <FilterPopover sceneFilters={sceneFilters} onFiltersChange={setActive} />
        </div>

        {filter.active.length > 0 && (
          <div className="px-4 pb-2">
            <FilterChipList filters={filter.active} onFiltersChange={setActive} />
          </div>
        )}
      </div>

      <div className="px-4 pt-3 pb-4">
        {filtered.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-6">No scenes match</p>
        ) : (
          <SceneSections
            sections={sections}
            activeImageId={activeImageId}
            onSceneClick={onSceneClick}
          />
        )}
      </div>
    </div>
  )
}

interface FilterControlProps {
  filter: FileFilter
  setFilter: SetFilter
}

function SearchBox({ filter, setFilter }: FilterControlProps) {
  const hasSearch = !!filter.text || filter.imageType !== 'all'

  return (
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
          className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground transition-colors"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}

function TypeToggle({ filter, setFilter }: FilterControlProps) {
  return (
    <div className="inline-flex rounded border border-border overflow-hidden shrink-0">
      {TYPE_OPTIONS.map(([label, val]) => (
        <button
          key={val}
          onClick={() => setFilter((f) => ({ ...f, imageType: val }))}
          className={`px-1.5 py-0.5 text-[10px] transition-colors ${
            filter.imageType === val
              ? 'bg-primary/10 text-primary font-medium'
              : 'text-muted-foreground hover:text-muted-foreground hover:bg-secondary/50'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

/** Always present; greyed when there is nothing to filter on. */
function FilterPopover({
  sceneFilters,
  onFiltersChange,
}: {
  sceneFilters: SceneFilters
  onFiltersChange: (active: FileFilter['active']) => void
}) {
  const [open, setOpen] = useState(false)
  const { filter, filterGroups } = sceneFilters
  // Whether there is anything to filter on, not whether a filter is applied
  const hasFilterableData = filterGroups.length > 0
  const activeCount = filter.active.length

  const triggerState =
    activeCount > 0
      ? 'bg-primary/10 text-primary border border-primary/40'
      : hasFilterableData
        ? 'text-muted-foreground hover:text-foreground hover:bg-secondary border border-transparent'
        : 'text-muted-foreground border border-transparent cursor-not-allowed'

  return (
    <Popover
      open={hasFilterableData ? open : false}
      onOpenChange={hasFilterableData ? setOpen : undefined}
    >
      <PopoverTrigger asChild>
        <button
          disabled={!hasFilterableData}
          className={`relative h-6 w-6 rounded flex items-center justify-center shrink-0 transition-colors ${triggerState}`}
          title={hasFilterableData ? 'Filter scenes' : 'No filterable dimensions'}
        >
          <SlidersHorizontal className="h-3 w-3" />
          {activeCount > 0 && (
            <span className="absolute -top-1 -right-1 h-4 min-w-4 px-1 rounded-full bg-primary text-[10px] font-bold text-primary-foreground flex items-center justify-center tabular-nums">
              {activeCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      {hasFilterableData && (
        <PopoverContent
          align="end"
          side="left"
          className="w-[min(400px,calc(100vw-2rem))] p-0 h-[min(480px,var(--radix-popover-content-available-height))] flex flex-col"
        >
          <FilterMenuContent
            groups={filterGroups}
            activeFilters={filter.active}
            onFiltersChange={onFiltersChange}
          />
        </PopoverContent>
      )}
    </Popover>
  )
}

function gridLabel(scene: Image): string | undefined {
  if (!scene.gridded || scene.image_type === 'scene') return undefined
  return scene.grid_width && scene.grid_height ? `${scene.grid_width}×${scene.grid_height}` : 'Grid'
}

function SceneSections({
  sections,
  activeImageId,
  onSceneClick,
}: {
  sections: SceneSection[]
  activeImageId: number
  onSceneClick: (scene: Image) => void
}) {
  return sections.map((section) => (
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
}
