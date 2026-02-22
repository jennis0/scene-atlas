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
import type { EditableFileState, TagData } from '@/types'
import { TagPicker } from './TagPicker'
import type { ParsedTagVocab } from './types'
import type { FileFilter, ActiveFilter, ImageTypeFilter } from './fileFilter'
import {
  FilterMenuContent,
  FilterChipList,
  type FilterOptionGroup,
} from '@/components/FilterMenuContent'

interface FileToolbarProps {
  files: EditableFileState[]
  filteredFiles: EditableFileState[]
  selection: Set<string>
  filter: FileFilter
  vocab: ParsedTagVocab[]
  onFilterChange: (v: FileFilter) => void
  onSelectAll: () => void
  onDeselectAll: () => void
  onBulkAddTag: (tag: TagData) => void
  onBulkSetGrid: (gridded: boolean | null, gridType: string | null) => void
  onBulkSetImageType: (v: 'battlemap' | 'scene') => void
  onBulkSetSubgroup: (v: string) => void
  onBulkExclude: () => void
  onMoveToNewGroup?: () => void
  excludeLabel?: string
  duplicateCount?: number
  skippedDuplicateCount?: number
  onBulkSetDuplicateAction?: (action: 'skip' | 'import') => void
  alwaysShowTypeToggle?: boolean
}

export function FileToolbar({
  files,
  filteredFiles,
  selection,
  filter,
  vocab,
  onFilterChange,
  onSelectAll,
  onDeselectAll,
  onBulkAddTag,
  onBulkSetGrid,
  onBulkSetImageType,
  onBulkSetSubgroup,
  onBulkExclude,
  onMoveToNewGroup,
  excludeLabel = 'Exclude',
  duplicateCount = 0,
  skippedDuplicateCount = 0,
  onBulkSetDuplicateAction,
  alwaysShowTypeToggle = false,
}: FileToolbarProps) {
  const [subgroupInput, setSubgroupInput] = useState('')
  const [subOpen, setSubOpen] = useState(false)
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

  const existingSubgroups = [
    ...new Set(files.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string)),
  ].sort()

  const applySubgroup = (value: string) => {
    onBulkSetSubgroup(value)
    setSubgroupInput('')
    setSubOpen(false)
  }

  // ── Build filter groups ──────────────────────────────────────────────────

  const nonExcludedFiles = files.filter((f) => !f.excluded && !f.outOfScope)

  const availableSubgroups = [
    ...new Set(nonExcludedFiles.filter((f) => f.subgroup).map((f) => f.subgroup as string)),
  ].sort()

  const gridStates: FilterOptionGroup['options'] = [
    { filterValue: 'square', label: 'Square grid', filterLabel: 'grid: Square' },
    { filterValue: 'hex', label: 'Hex grid', filterLabel: 'grid: Hex' },
    { filterValue: 'gridded', label: 'Any gridded', filterLabel: 'grid: Gridded' },
    { filterValue: 'gridless', label: 'Gridless', filterLabel: 'grid: Gridless' },
    { filterValue: 'unknown', label: 'Unknown', filterLabel: 'grid: Unknown' },
  ]

  const tagFreq = new Map<string, { category: string; value: string; count: number }>()
  for (const f of nonExcludedFiles) {
    for (const t of f.tags) {
      const key = `${t.category}:${t.value}`
      const entry = tagFreq.get(key)
      if (entry) entry.count++
      else tagFreq.set(key, { category: t.category, value: t.value, count: 1 })
    }
  }

  const tagsByCategory = new Map<string, Array<{ key: string; value: string; count: number }>>()
  for (const [key, entry] of tagFreq) {
    const arr = tagsByCategory.get(entry.category) ?? []
    arr.push({ key, value: entry.value, count: entry.count })
    tagsByCategory.set(entry.category, arr)
  }
  for (const arr of tagsByCategory.values()) {
    arr.sort((a, b) => b.count - a.count)
  }

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

  const hasMixedTypes = new Set(nonExcludedFiles.map((f) => f.image_type ?? 'battlemap')).size > 1

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

  filterGroups.push({
    id: 'gridded',
    label: 'Grid state',
    type: 'gridded',
    options: gridStates,
  })

  for (const [category, tags] of tagsByCategory.entries()) {
    filterGroups.push({
      id: category,
      label: category,
      type: 'tag',
      options: tags.map((t) => ({
        filterValue: `${category}:${t.value}`,
        label: t.value,
        filterLabel: `${category}: ${t.value}`,
        count: t.count,
      })),
    })
  }

  const handleFiltersChange = (newFilters: ActiveFilter[]) => {
    onFilterChange({ ...filter, active: newFilters })
  }

  // ── Render ────────────────────────────────────────────────────────────────

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
              placeholder="Filter maps…"
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

          {(hasMixedTypes || alwaysShowTypeToggle) && (
            <TypeToggle
              value={filter.imageType}
              onChange={(v) => onFilterChange({ ...filter, imageType: v })}
            />
          )}

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
            <PopoverContent align="end" className="w-80 p-0 h-72 flex flex-col">
              <FilterMenuContent
                groups={filterGroups}
                activeFilters={filter.active}
                onFiltersChange={handleFiltersChange}
              />
            </PopoverContent>
          </Popover>
        </div>

        {/* Bulk actions — only shown when something is selected */}
        {totalSelected > 0 && (
          <div className="flex items-center gap-0.5 shrink-0">
            {vocab.length > 0 && <TagPicker vocab={vocab} existingTags={[]} onAdd={onBulkAddTag} />}

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

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1">
                  Grid <ChevronDown className="h-3 w-3" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onBulkSetGrid(true, 'square')}>
                  Square
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onBulkSetGrid(true, 'hex')}>Hex</DropdownMenuItem>
                <DropdownMenuItem onClick={() => onBulkSetGrid(false, null)}>
                  Gridless
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onBulkSetGrid(null, null)}>
                  Unknown
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <Popover open={subOpen} onOpenChange={setSubOpen}>
              <PopoverTrigger asChild>
                <button className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1">
                  Sub <ChevronDown className="h-3 w-3" />
                </button>
              </PopoverTrigger>
              <PopoverContent
                align="end"
                className="w-52 p-0"
                onOpenAutoFocus={(e: Event) => {
                  e.preventDefault()
                }}
              >
                {existingSubgroups.length > 0 && (
                  <>
                    <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-wider">
                      Existing
                    </div>
                    {existingSubgroups.map((sv) => (
                      <button
                        key={sv}
                        onClick={() => applySubgroup(sv)}
                        className="w-full text-left px-3 py-1.5 text-sm text-foreground hover:bg-secondary capitalize transition-colors"
                      >
                        {sv}
                      </button>
                    ))}
                    <div className="h-px bg-border/50 my-1" />
                  </>
                )}
                <div className="p-2 flex gap-1.5">
                  <input
                    autoFocus={existingSubgroups.length === 0}
                    value={subgroupInput}
                    onChange={(e) => setSubgroupInput(e.target.value)}
                    placeholder="New subgroup…"
                    className="flex-1 min-w-0 h-7 px-2 text-sm bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                    onKeyDown={(e) => {
                      e.stopPropagation()
                      if (e.key === 'Enter' && subgroupInput.trim())
                        applySubgroup(subgroupInput.trim())
                      if (e.key === 'Escape') setSubOpen(false)
                    }}
                  />
                  <button
                    className="h-7 px-2.5 text-xs shrink-0 rounded border border-border bg-secondary text-muted-foreground hover:text-foreground transition-colors"
                    onClick={() => {
                      if (subgroupInput.trim()) applySubgroup(subgroupInput.trim())
                    }}
                  >
                    Set
                  </button>
                </div>
              </PopoverContent>
            </Popover>

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
              {excludeLabel}
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

      <FilterChipList filters={filter.active} onFiltersChange={handleFiltersChange} />
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
