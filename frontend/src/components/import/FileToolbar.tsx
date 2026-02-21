import { useEffect, useRef, useState } from 'react'
import { Search, X, ChevronDown, FolderPlus, SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import type { EditableFileState, TagData } from '@/types'
import { TagPicker } from './TagPicker'
import type { ParsedTagVocab } from './types'
import type { FileFilter, ActiveFilter } from './fileFilter'
import { FilterMenuContent, FilterChipList, type FilterOptionGroup } from '@/components/FilterMenuContent'

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
  onBulkSetGrid: (v: boolean | null) => void
  onBulkSetSubVariant: (v: string) => void
  onBulkExclude: () => void
  onMoveToNewGroup: () => void
  excludeLabel?: string
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
  onBulkSetSubVariant,
  onBulkExclude,
  onMoveToNewGroup,
  excludeLabel = 'Exclude',
}: FileToolbarProps) {
  const checkboxRef = useRef<HTMLInputElement>(null)
  const subInputRef = useRef<HTMLInputElement>(null)
  const [subVariantInput, setSubVariantInput] = useState('')
  const [subOpen, setSubOpen] = useState(false)
  const [filterOpen, setFilterOpen] = useState(false)

  const visibleNonExcluded = filteredFiles.filter((f) => !f.excluded)
  const selectedVisible = visibleNonExcluded.filter((f) => selection.has(f.relative_path))
  const totalSelected = files.filter((f) => !f.excluded && selection.has(f.relative_path)).length
  const totalNonExcluded = files.filter((f) => !f.excluded).length
  const isAllSelected = visibleNonExcluded.length > 0 && selectedVisible.length === visibleNonExcluded.length
  const isIndeterminate = selectedVisible.length > 0 && !isAllSelected

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = isIndeterminate
    }
  }, [isIndeterminate])

  const handleCheckboxChange = () => {
    if (isAllSelected || isIndeterminate) {
      onDeselectAll()
    } else {
      onSelectAll()
    }
  }

  const existingSubVariants = [...new Set(
    files.filter((f) => !f.excluded && f.sub_variant).map((f) => f.sub_variant as string)
  )].sort()

  const applySubVariant = (value: string) => {
    onBulkSetSubVariant(value)
    setSubVariantInput('')
    setSubOpen(false)
  }

  // ── Build filter groups ──────────────────────────────────────────────────

  const nonExcludedFiles = files.filter((f) => !f.excluded)

  const availableSubVariants = [...new Set(
    nonExcludedFiles.filter((f) => f.sub_variant).map((f) => f.sub_variant as string)
  )].sort()

  const gridStates: FilterOptionGroup['options'] = [
    { filterValue: 'gridded',  label: 'Gridded',  filterLabel: 'grid: Gridded' },
    { filterValue: 'gridless', label: 'Gridless', filterLabel: 'grid: Gridless' },
    { filterValue: 'unknown',  label: 'Unknown',  filterLabel: 'grid: Unknown' },
  ]

  // Aggregate tag frequencies across all non-excluded files (no top-5 cap — use search to navigate)
  const tagFreq = new Map<string, { category: string; value: string; count: number }>()
  for (const f of nonExcludedFiles) {
    for (const t of f.tags) {
      const key = `${t.category}:${t.value}`
      const entry = tagFreq.get(key)
      if (entry) entry.count++
      else tagFreq.set(key, { category: t.category, value: t.value, count: 1 })
    }
  }

  // Group by category, sort by frequency
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

  if (availableSubVariants.length > 0) {
    filterGroups.push({
      id: 'subVariant',
      label: 'Sub-variant',
      type: 'subVariant',
      options: availableSubVariants.map((sv) => ({
        filterValue: sv,
        label: sv,
        filterLabel: `sub: ${sv}`,
      })),
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
    <div className="flex flex-col py-2 border-b border-slate-100 flex-shrink-0">
      {/* Main toolbar row */}
      <div className="flex items-center gap-2">
        {/* Select-all checkbox + count */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <input
            ref={checkboxRef}
            type="checkbox"
            checked={isAllSelected}
            onChange={handleCheckboxChange}
            disabled={visibleNonExcluded.length === 0}
            className="h-3.5 w-3.5 rounded border-slate-300 cursor-pointer accent-emerald-600 disabled:opacity-40"
            title="Select all visible"
          />
          <span className="text-xs text-slate-400 tabular-nums whitespace-nowrap">
            {totalSelected > 0
              ? <><span className="text-slate-600 font-medium">{totalSelected}</span> / {totalNonExcluded}</>
              : <>{totalNonExcluded} file{totalNonExcluded !== 1 ? 's' : ''}</>
            }
          </span>
        </div>

        {/* Text search + filter popover */}
        <div className="relative flex-1 min-w-0 flex items-center gap-1">
          <div className="relative flex-1 min-w-0">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-300 pointer-events-none" />
            <input
              value={filter.text}
              onChange={(e) => onFilterChange({ ...filter, text: e.target.value })}
              placeholder="Filter maps…"
              className="w-full h-7 pl-8 pr-7 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-300 focus:border-emerald-300 text-slate-600 placeholder:text-slate-300"
            />
            {filter.text && (
              <button
                onClick={() => onFilterChange({ ...filter, text: '' })}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-300 hover:text-slate-500 transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Filter popover */}
          <Popover open={filterOpen} onOpenChange={setFilterOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className={`h-7 px-2 flex-shrink-0 gap-1 ${filter.active.length > 0 ? 'text-emerald-600' : 'text-slate-400 hover:text-slate-600'}`}
                title="Add filters"
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                {filter.active.length > 0 && (
                  <span className="text-xs font-medium">{filter.active.length}</span>
                )}
              </Button>
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
          <div className="flex items-center gap-1 flex-shrink-0">
            {/* Bulk add tag */}
            {vocab.length > 0 && (
              <TagPicker
                vocab={vocab}
                existingTags={[]}
                onAdd={onBulkAddTag}
              />
            )}

            {/* Bulk grid */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-slate-500 gap-1">
                  Grid <ChevronDown className="h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onBulkSetGrid(true)}>Grid</DropdownMenuItem>
                <DropdownMenuItem onClick={() => onBulkSetGrid(false)}>Gridless</DropdownMenuItem>
                <DropdownMenuItem onClick={() => onBulkSetGrid(null)}>Unknown</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Bulk sub-variant */}
            <Popover open={subOpen} onOpenChange={setSubOpen}>
              <PopoverTrigger asChild>
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-slate-500 gap-1">
                  Sub <ChevronDown className="h-3 w-3" />
                </Button>
              </PopoverTrigger>
              <PopoverContent
                align="end"
                className="w-52 p-0"
                onOpenAutoFocus={(e: Event) => { e.preventDefault(); subInputRef.current?.focus() }}
              >
                {existingSubVariants.length > 0 && (
                  <>
                    <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                      Existing
                    </div>
                    {existingSubVariants.map((sv) => (
                      <button
                        key={sv}
                        onClick={() => applySubVariant(sv)}
                        className="w-full text-left px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 capitalize transition-colors"
                      >
                        {sv}
                      </button>
                    ))}
                    <div className="h-px bg-slate-100 my-1" />
                  </>
                )}
                <div className="p-2 flex gap-1.5">
                  <input
                    ref={subInputRef}
                    value={subVariantInput}
                    onChange={(e) => setSubVariantInput(e.target.value)}
                    placeholder="New sub-variant…"
                    className="flex-1 min-w-0 h-7 px-2 text-sm border border-slate-200 rounded focus:outline-none focus:ring-1 focus:ring-emerald-300 focus:border-emerald-300"
                    onKeyDown={(e) => {
                      e.stopPropagation()
                      if (e.key === 'Enter' && subVariantInput.trim()) applySubVariant(subVariantInput.trim())
                      if (e.key === 'Escape') setSubOpen(false)
                    }}
                  />
                  <Button
                    size="sm"
                    className="h-7 text-xs flex-shrink-0"
                    onClick={() => { if (subVariantInput.trim()) applySubVariant(subVariantInput.trim()) }}
                  >
                    Set
                  </Button>
                </div>
              </PopoverContent>
            </Popover>

            {/* Move to new group */}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-slate-500 hover:text-slate-700 gap-1"
              onClick={onMoveToNewGroup}
              title="Move selected to new group"
            >
              <FolderPlus className="h-3.5 w-3.5" />
              Split
            </Button>

            {/* Exclude / Delete */}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-red-400 hover:text-red-600 hover:bg-red-50 gap-1"
              onClick={onBulkExclude}
            >
              <X className="h-3.5 w-3.5" />
              {excludeLabel}
            </Button>
          </div>
        )}
      </div>

      {/* Active filter chips */}
      <FilterChipList filters={filter.active} onFiltersChange={handleFiltersChange} />
    </div>
  )
}
