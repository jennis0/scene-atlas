import { useState } from 'react'
import { Search, X, ChevronDown, FolderPlus, SlidersHorizontal, Copy } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { EditableFileState } from '@/types'
import type { FileFilter, ImageTypeFilter } from './fileFilter'
import {
  FilterMenuContent,
  FilterChipList,
  type FilterOptionGroup,
} from '@/components/FilterMenuContent'

interface ImportFileToolbarProps {
  files: EditableFileState[]
  filteredFiles: EditableFileState[]
  selection: Set<string>
  filter: FileFilter
  onFilterChange: (v: FileFilter) => void
  onSelectAll: () => void
  onDeselectAll: () => void
  onBulkSetImageType: (v: 'battlemap' | 'scene') => void
  onBulkExclude: () => void
  onMoveToNewGroup?: () => void
  duplicateCount?: number
  skippedDuplicateCount?: number
  onBulkSetDuplicateAction?: (action: 'skip' | 'import') => void
}

export function ImportFileToolbar({
  files,
  filteredFiles,
  selection,
  filter,
  onFilterChange,
  onSelectAll,
  onDeselectAll,
  onBulkSetImageType,
  onBulkExclude,
  onMoveToNewGroup,
  duplicateCount = 0,
  skippedDuplicateCount = 0,
  onBulkSetDuplicateAction,
}: ImportFileToolbarProps) {
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

  // ── Build filter groups (subgroup + media type only) ────────────────────────

  const nonExcludedFiles = files.filter((f) => !f.excluded && !f.outOfScope)

  const availableSubgroups = [
    ...new Set(nonExcludedFiles.filter((f) => f.subgroup).map((f) => f.subgroup as string)),
  ].sort()

  const hasMixedTypes = new Set(nonExcludedFiles.map((f) => f.image_type ?? 'battlemap')).size > 1

  const filterGroups: FilterOptionGroup[] = []

  if (availableSubgroups.length > 0) {
    filterGroups.push({
      id: 'subgroup',
      label: 'Subgroup',
      type: 'subgroup',
      options: availableSubgroups.map((sv) => ({
        filterValue: sv,
        label: sv,
        filterLabel: `subgroup: ${sv}`,
      })),
    })
  }

  const mediaTypes = [...new Set(nonExcludedFiles.map((f) => f.media_type ?? 'image'))]
  if (mediaTypes.length > 1) {
    filterGroups.push({
      id: 'media_type',
      label: 'Media',
      type: 'media_type',
      options: [
        { filterValue: 'image', label: 'Images', filterLabel: 'media: Images' },
        { filterValue: 'video', label: 'Videos', filterLabel: 'media: Videos' },
      ],
    })
  }

  const hasFilterGroups = filterGroups.length > 0

  const handleFiltersChange = (newFilters: typeof filter.active) => {
    onFilterChange({ ...filter, active: newFilters })
  }

  // ── Render ──────────────────────────────────────────────────────────────────

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
              placeholder="Filter files…"
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

          {hasMixedTypes && (
            <TypeToggle
              value={filter.imageType}
              onChange={(v) => onFilterChange({ ...filter, imageType: v })}
            />
          )}

          {hasFilterGroups && (
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
        {totalSelected > 0 && (
          <div className="flex items-center gap-0.5 shrink-0">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1">
                  Type <ChevronDown className="h-3 w-3" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onBulkSetImageType('battlemap')}>
                  Battlemap
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onBulkSetImageType('scene')}>
                  Scene
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {onMoveToNewGroup && (
              <button
                className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1"
                onClick={onMoveToNewGroup}
                title="Move selected to new group"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                Split
              </button>
            )}

            <button
              className="h-7 px-2 rounded text-xs text-destructive/70 hover:text-destructive hover:bg-destructive/10 transition-colors flex items-center gap-1"
              onClick={onBulkExclude}
            >
              <X className="h-3.5 w-3.5" />
              Exclude
            </button>
          </div>
        )}
      </div>

      {/* Duplicate bulk controls */}
      {duplicateCount > 0 && onBulkSetDuplicateAction && (
        <div className="flex items-center gap-2 pt-1.5">
          <Copy className="h-3.5 w-3.5 text-amber-400/70 shrink-0" />
          <span className="text-xs text-amber-400/80">
            {skippedDuplicateCount}/{duplicateCount} duplicate{duplicateCount !== 1 ? 's' : ''}{' '}
            skipped
          </span>
          <button
            className="text-[11px] rounded border border-amber-500/30 px-1.5 py-0.5 text-amber-400/80 hover:bg-amber-500/10 transition-colors"
            onClick={() => onBulkSetDuplicateAction(skippedDuplicateCount > 0 ? 'import' : 'skip')}
          >
            {skippedDuplicateCount > 0 ? 'Include all duplicates' : 'Skip all duplicates'}
          </button>
        </div>
      )}

      {filter.active.length > 0 && (
        <div className="mt-1.5">
          <FilterChipList filters={filter.active} onFiltersChange={handleFiltersChange} />
        </div>
      )}
    </div>
  )
}

function TypeToggle({
  value,
  onChange,
}: {
  value: ImageTypeFilter
  onChange: (v: ImageTypeFilter) => void
}) {
  const opts: { label: string; val: ImageTypeFilter }[] = [
    { label: 'All', val: 'all' },
    { label: 'Maps', val: 'battlemap' },
    { label: 'Scenes', val: 'scene' },
  ]
  return (
    <div className="inline-flex rounded border border-border overflow-hidden shrink-0">
      {opts.map((opt) => (
        <button
          key={opt.val}
          onClick={() => onChange(opt.val)}
          className={`px-1.5 py-0.5 text-[11px] transition-colors ${
            value === opt.val
              ? 'bg-secondary text-foreground font-medium'
              : 'text-muted-foreground/60 hover:text-muted-foreground hover:bg-secondary/50'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
