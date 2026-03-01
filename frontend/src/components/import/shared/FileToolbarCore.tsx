import { useState, type ReactNode } from 'react'
import { Search, X, SlidersHorizontal } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { EditableFileState } from '@/types'
import type { FileFilter, ActiveFilter } from '../fileFilter'
import { TypeToggle } from './TypeToggle'
import {
  FilterMenuContent,
  FilterChipList,
  type FilterOptionGroup,
} from '@/components/FilterMenuContent'

interface FileToolbarCoreProps {
  files: EditableFileState[]
  filteredFiles: EditableFileState[]
  selection: Set<string>
  filter: FileFilter
  filterGroups: FilterOptionGroup[]
  onFilterChange: (v: FileFilter) => void
  onSelectAll: () => void
  onDeselectAll: () => void
  showTypeToggle?: boolean
  /** When true, always show the filter button even if filterGroups is empty */
  alwaysShowFilterButton?: boolean
  searchPlaceholder?: string
  /** Rendered inside the bulk actions area when items are selected */
  bulkActions?: ReactNode
  /** Duplicate controls row — rendered below the main toolbar row */
  duplicateControls?: ReactNode
}

export function FileToolbarCore({
  files,
  filteredFiles,
  selection,
  filter,
  filterGroups,
  onFilterChange,
  onSelectAll,
  onDeselectAll,
  showTypeToggle = false,
  alwaysShowFilterButton = false,
  searchPlaceholder = 'Filter files…',
  bulkActions,
  duplicateControls,
}: FileToolbarCoreProps) {
  const [filterOpen, setFilterOpen] = useState(false)

  const visibleNonExcluded = filteredFiles.filter((f) => !f.excluded && !f.outOfScope)
  const selectedVisible = visibleNonExcluded.filter((f) => selection.has(f.relative_path))
  const totalSelected = files.filter(
    (f) => !f.excluded && !f.outOfScope && selection.has(f.relative_path),
  ).length
  const totalNonExcluded = files.filter((f) => !f.excluded && !f.outOfScope).length
  const isAllSelected =
    visibleNonExcluded.length > 0 && selectedVisible.length === visibleNonExcluded.length
  const isIndeterminate = selectedVisible.length > 0 && !isAllSelected

  const handleCheckboxChange = () => {
    if (isAllSelected || isIndeterminate) {
      onDeselectAll()
    } else {
      onSelectAll()
    }
  }

  const handleFiltersChange = (newFilters: ActiveFilter[]) => {
    onFilterChange({ ...filter, active: newFilters })
  }

  const showFilterButton = alwaysShowFilterButton || filterGroups.length > 0

  return (
    <div className="flex flex-col py-2 border-b border-border/30 shrink-0">
      {/* Main toolbar row */}
      <div className="flex items-center gap-2">
        {/* Select-all checkbox + count */}
        <div className="flex items-center gap-2 shrink-0">
          <Checkbox
            checked={isIndeterminate ? 'indeterminate' : isAllSelected}
            onCheckedChange={handleCheckboxChange}
            disabled={visibleNonExcluded.length === 0}
            className="h-3.5 w-3.5 rounded-[3px]"
          />
          <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
            {totalSelected > 0 ? (
              <>
                <span className="text-foreground font-medium">{totalSelected}</span> /{' '}
                {totalNonExcluded}
              </>
            ) : (
              <>
                {totalNonExcluded} file{totalNonExcluded !== 1 ? 's' : ''}
              </>
            )}
          </span>
        </div>

        {/* Search + filter */}
        <div className="relative flex-1 min-w-0 flex items-center gap-1">
          <div className="relative flex-1 min-w-0">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/40 pointer-events-none" />
            <input
              value={filter.text}
              onChange={(e) => onFilterChange({ ...filter, text: e.target.value })}
              placeholder={searchPlaceholder}
              className="w-full h-7 pl-8 pr-7 text-sm bg-secondary border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary/40 text-foreground placeholder:text-muted-foreground"
            />
            {(filter.text || filter.imageType !== 'all') && (
              <button
                onClick={() => onFilterChange({ ...filter, text: '', imageType: 'all' })}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/40 hover:text-muted-foreground transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {showTypeToggle && (
            <TypeToggle
              value={filter.imageType}
              onChange={(v) => onFilterChange({ ...filter, imageType: v })}
            />
          )}

          {showFilterButton && (
            <Popover open={filterOpen} onOpenChange={setFilterOpen}>
              <PopoverTrigger asChild>
                <button
                  className={`h-7 w-7 rounded flex items-center justify-center shrink-0 transition-colors ${
                    filter.active.length > 0
                      ? 'text-primary bg-primary/20 border border-primary/40'
                      : 'text-muted-foreground hover:text-foreground hover:bg-secondary border border-transparent'
                  }`}
                  title="Add filters"
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                </button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-[400px] p-0 h-[480px] flex flex-col">
                <FilterMenuContent
                  groups={filterGroups}
                  activeFilters={filter.active}
                  onFiltersChange={handleFiltersChange}
                />
              </PopoverContent>
            </Popover>
          )}
        </div>

        {/* Bulk actions — only shown when something is selected */}
        {totalSelected > 0 && bulkActions && (
          <div className="flex items-center gap-0.5 shrink-0">{bulkActions}</div>
        )}
      </div>

      {/* Duplicate controls row */}
      {duplicateControls}

      {/* Active filter chips */}
      {filter.active.length > 0 && (
        <div className="mt-1.5">
          <FilterChipList filters={filter.active} onFiltersChange={handleFiltersChange} />
        </div>
      )}
    </div>
  )
}
