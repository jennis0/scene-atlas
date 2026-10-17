import { useState } from 'react'
import { X, ChevronDown, FolderPlus, Copy } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { onInlineEditKey } from '@/lib/inlineEditKeys'
import type { EditableFileState, TagData } from '@/types'
import { TagPicker } from './TagPicker'
import type { ParsedTagVocab } from './types'
import { buildTagFilterGroups, type FileFilter } from './fileFilter'
import type { FilterOptionGroup } from '@/components/FilterMenuContent'
import { FileToolbarCore } from './shared/FileToolbarCore'

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

  const existingSubgroups = [
    ...new Set(files.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string)),
  ].sort()

  const applySubgroup = (value: string) => {
    onBulkSetSubgroup(value)
    setSubgroupInput('')
    setSubOpen(false)
  }

  // Build filter groups

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

  filterGroups.push(...buildTagFilterGroups(nonExcludedFiles))

  // Slots

  const bulkActions = (
    <>
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
          <DropdownMenuItem onClick={() => onBulkSetImageType('scene')}>Scene</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1">
            Grid <ChevronDown className="h-3 w-3" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => onBulkSetGrid(true, 'square')}>Square</DropdownMenuItem>
          <DropdownMenuItem onClick={() => onBulkSetGrid(true, 'hex')}>Hex</DropdownMenuItem>
          <DropdownMenuItem onClick={() => onBulkSetGrid(false, null)}>Gridless</DropdownMenuItem>
          <DropdownMenuItem onClick={() => onBulkSetGrid(null, null)}>Unknown</DropdownMenuItem>
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
              <div className="px-3 pt-2.5 pb-1 text-xs font-semibold text-muted-foreground">
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
              className="flex-1 min-w-0 h-7 px-2 text-sm bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground"
              onKeyDown={(e) => {
                e.stopPropagation()
                onInlineEditKey(e, {
                  onEnter: () => {
                    if (subgroupInput.trim()) applySubgroup(subgroupInput.trim())
                  },
                  onEscape: () => setSubOpen(false),
                })
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
    </>
  )

  const duplicateControls =
    duplicateCount > 0 && onBulkSetDuplicateAction ? (
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
    ) : undefined

  return (
    <FileToolbarCore
      files={files}
      filteredFiles={filteredFiles}
      selection={selection}
      filter={filter}
      filterGroups={filterGroups}
      onFilterChange={onFilterChange}
      onSelectAll={onSelectAll}
      onDeselectAll={onDeselectAll}
      showTypeToggle={hasMixedTypes || alwaysShowTypeToggle}
      alwaysShowFilterButton
      searchPlaceholder="Filter maps…"
      bulkActions={bulkActions}
      duplicateControls={duplicateControls}
    />
  )
}
