import { ArrowUpDown, Grid2x2, Grid3x3, Loader2, Pencil, X } from 'lucide-react'
import { FilterChipList } from '@/components/FilterMenuContent'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  RELEVANCE_MIN,
  RELEVANCE_MAX,
  RELEVANCE_STEP,
  TILE_WIDTH,
  relevanceToPercent,
} from '@/lib/constants'
import { SORT_OPTIONS } from '@/hooks/useGallerySearch'
import type { UseGallerySearchReturn } from '@/hooks/useGallerySearch'

type Search = UseGallerySearchReturn & { editAllLoading?: boolean }

interface GalleryResultsBarProps {
  search: Search
  displayImageCount: number
  onOpenMassEdit: () => void
  /** Individual-view tile width in px */
  tileWidth: number
  onTileWidthChange: (width: number) => void
  /** Sits in the search row (compact layout) rather than on its own row below it */
  inline?: boolean
}

/** Under the search: active filter chips, then the result count, sort, Edit all and relevance. */
export function GalleryResultsBar({
  search,
  displayImageCount,
  onOpenMassEdit,
  tileWidth,
  onTileWidthChange,
  inline = false,
}: GalleryResultsBarProps) {
  const { filters, handleFiltersChange, hasActiveSearch, clearAll } = search
  return (
    <div
      className={`flex flex-wrap items-center gap-x-4 gap-y-1 ${inline ? 'ml-auto' : 'pb-4 min-h-[32px]'}`}
    >
      <div className="flex-1 min-w-0 flex items-center gap-1.5 flex-wrap">
        <FilterChipList
          filters={filters}
          onFiltersChange={handleFiltersChange}
          showClearAll={false}
        />
        {hasActiveSearch && (
          <button
            onClick={clearAll}
            className="relative target-24 text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 ml-1"
          >
            <X className="h-2.5 w-2.5" />
            Clear all
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center ml-auto shrink-0 text-xs text-muted-foreground gap-0">
        <ResultCount search={search} />
        <Separator />
        <SortMenu search={search} />
        {search.viewMode === 'individual' && (
          <>
            <Separator />
            <TileSizeSlider width={tileWidth} onChange={onTileWidthChange} />
          </>
        )}
        <EditAllButton
          search={search}
          displayImageCount={displayImageCount}
          onOpenMassEdit={onOpenMassEdit}
        />
        {search.showRelevanceSlider && (
          <>
            <Separator />
            <RelevanceSlider minScore={search.minScore} setMinScore={search.setMinScore} />
          </>
        )}
      </div>
    </div>
  )
}

function Separator() {
  return (
    <span aria-hidden="true" className="text-border/60 px-1.5">
      &middot;
    </span>
  )
}

const plural = (n: number, word: string) => `${n} ${word}${n !== 1 ? 's' : ''}`

function resultCountText(search: Search): string {
  const { isSearching, viewMode, totalGroups, hasActiveSearch, facets } = search
  if (isSearching) return ''
  if (viewMode === 'grouped') return plural(totalGroups, 'group')
  if (!hasActiveSearch) return `${facets?.total_images ?? 0} scenes`
  const { filteredCount, totalBeforeFilter, searchModeSuffix } = search
  return search.showRelevanceSlider
    ? `${filteredCount} / ${plural(totalBeforeFilter, 'result')}${searchModeSuffix}`
    : `${plural(filteredCount, 'result')}${searchModeSuffix}`
}

function ResultCount({ search }: { search: Search }) {
  // Always mounted so screen readers hear each new count after a search
  return (
    <span role="status" className="tabular-nums">
      {resultCountText(search)}
    </span>
  )
}

function SortMenu({ search }: { search: Search }) {
  const { sortKey, handleSortChange, submittedQuery } = search
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="relative target-24 flex items-center gap-1 hover:text-foreground transition-colors">
          {SORT_OPTIONS.find((o) => `${o.value}:${o.dir}` === sortKey)?.label ?? 'Sort'}
          <ArrowUpDown className="h-2.5 w-2.5 opacity-50" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuRadioGroup value={sortKey} onValueChange={handleSortChange}>
          {SORT_OPTIONS.map((opt) => {
            const key = `${opt.value}:${opt.dir}`
            return (
              <DropdownMenuRadioItem
                key={key}
                value={key}
                disabled={opt.queryOnly && !submittedQuery}
              >
                {opt.label}
              </DropdownMenuRadioItem>
            )
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

const EDIT_ALL_CLASS =
  'relative target-24 flex items-center gap-1.5 hover:text-foreground transition-colors'

/** Small-grid icon · slider · large-grid icon, for the individual view's tile width. */
function TileSizeSlider({ width, onChange }: { width: number; onChange: (w: number) => void }) {
  const fill = ((width - TILE_WIDTH.min) / (TILE_WIDTH.max - TILE_WIDTH.min)) * 100
  return (
    <div className="flex items-center gap-1.5" title="Tile size">
      <Grid3x3 aria-hidden="true" className="h-3 w-3" />
      <input
        type="range"
        min={TILE_WIDTH.min}
        max={TILE_WIDTH.max}
        step={TILE_WIDTH.step}
        value={width}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="Tile size"
        aria-valuetext={`${width} pixels wide`}
        className="range w-16"
        style={{ '--fill': `${fill}%` } as React.CSSProperties}
      />
      <Grid2x2 aria-hidden="true" className="h-3.5 w-3.5" />
    </div>
  )
}

/** Bulk-edit everything in the results. Grouped view caps it at 500 groups. */
function EditAllButton({
  search,
  displayImageCount,
  onOpenMassEdit,
}: Pick<GalleryResultsBarProps, 'search' | 'displayImageCount' | 'onOpenMassEdit'>) {
  const grouped = search.viewMode === 'grouped'
  const count = grouped ? search.totalGroups : displayImageCount
  if (count === 0) return null

  if (grouped && count > 500) {
    return (
      <>
        <Separator />
        {/* Focusable, so keyboard users can reach the explanation too */}
        <button
          type="button"
          aria-disabled="true"
          title={`Too many groups (${count}) — apply filters to narrow below 500`}
          className="relative target-24 flex items-center gap-1.5 cursor-not-allowed opacity-50"
        >
          <Pencil className="h-3 w-3" />
          Edit all ({count})
        </button>
      </>
    )
  }

  const loading = grouped && search.editAllLoading
  const title = grouped
    ? loading
      ? 'Loading images...'
      : 'Bulk-edit all groups in current results'
    : 'Bulk-edit all scenes in current results'
  return (
    <>
      <Separator />
      <button
        onClick={onOpenMassEdit}
        disabled={loading}
        title={title}
        className={`${EDIT_ALL_CLASS} disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Pencil className="h-3 w-3" />}
        Edit all ({count})
      </button>
    </>
  )
}

function RelevanceSlider({
  minScore,
  setMinScore,
}: {
  minScore: number
  setMinScore: (score: number) => void
}) {
  const shown = minScore > 0 ? `${relevanceToPercent(minScore)}%` : 'All'
  const fill = ((minScore - RELEVANCE_MIN) / (RELEVANCE_MAX - RELEVANCE_MIN)) * 100
  return (
    <div className="flex items-center gap-2" title="Minimum relevance threshold">
      <span>Relevance</span>
      <input
        type="range"
        min={RELEVANCE_MIN}
        max={RELEVANCE_MAX}
        step={RELEVANCE_STEP}
        value={minScore}
        onChange={(e) => setMinScore(parseFloat(e.target.value))}
        aria-label="Minimum relevance"
        aria-valuetext={minScore > 0 ? shown : 'All results'}
        className="range w-20"
        style={{ '--fill': `${fill}%` } as React.CSSProperties}
      />
      <span className="tabular-nums w-7 text-right">{shown}</span>
    </div>
  )
}
