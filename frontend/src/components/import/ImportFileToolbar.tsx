import { X, ChevronDown, FolderPlus, Copy } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { EditableFileState } from '@/types'
import type { FileFilter } from './fileFilter'
import type { FilterOptionGroup } from '@/components/FilterMenuContent'
import { FileToolbarCore } from './shared/FileToolbarCore'

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

  // ── Slots ────────────────────────────────────────────────────────────────

  const bulkActions = (
    <>
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
      showTypeToggle={hasMixedTypes}
      searchPlaceholder="Filter files…"
      bulkActions={bulkActions}
      duplicateControls={duplicateControls}
    />
  )
}
