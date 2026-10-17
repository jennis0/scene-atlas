import { X, FolderPlus, Copy } from 'lucide-react'
import type { EditableFileState, TagData } from '@/types'
import { BulkEditControls } from './BulkEditControls'
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
  const existingSubgroups = [
    ...new Set(files.filter((f) => !f.excluded && f.subgroup).map((f) => f.subgroup as string)),
  ].sort()

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
      <BulkEditControls
        vocab={vocab}
        existingSubgroups={existingSubgroups}
        onAddTag={onBulkAddTag}
        onSetGrid={onBulkSetGrid}
        onSetImageType={onBulkSetImageType}
        onSetSubgroup={onBulkSetSubgroup}
      />

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
        <Copy className="h-3.5 w-3.5 text-warning shrink-0" />
        <span className="text-xs text-warning">
          {skippedDuplicateCount}/{duplicateCount} duplicate{duplicateCount !== 1 ? 's' : ''}{' '}
          skipped
        </span>
        <button
          className="text-2xs rounded border border-warning/30 px-1.5 py-0.5 text-warning hover:bg-warning/10 transition-colors"
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
