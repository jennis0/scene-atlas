import { Search } from 'lucide-react'
import { FileCard } from '@/components/import/FileCard'
import { SubgroupHeading } from '@/components/SubgroupHeading'
import { DroppableSubgroupSection, type ActiveDragState } from '@/components/import/shared/dnd'
import type { EditableFileState, ParsedTagVocab } from '@/types'

interface EditGroupFileGridProps {
  files: EditableFileState[]
  /** Images in the group but outside the edit scope, shown read-only for context. */
  outOfScopeFiles: EditableFileState[]
  renderCard: (file: EditableFileState) => React.ReactNode
  hasActiveFilter: boolean
  activeDrag: ActiveDragState | null
  existingSubgroups: string[]
  /** Subgroup headings can be renamed or cleared only when one group is shown. */
  canEditSubgroups: boolean
  editingSubgroup: string | null
  onEditingSubgroupChange: (subgroup: string | null) => void
  onRenameSubgroup: (from: string, to: string) => void
  onClearSubgroup: (subgroup: string) => void
  vocab: ParsedTagVocab[]
  onUpdateOutOfScope: (file: EditableFileState, updates: Partial<EditableFileState>) => void
}

/** Unlabelled first, then alphabetical. */
function subgroupOrder(files: EditableFileState[]): (string | null)[] {
  return [...new Set(files.map((f) => f.subgroup))].sort((a, b) => {
    if (a === null) return -1
    if (b === null) return 1
    return a.localeCompare(b)
  })
}

export function EditGroupFileGrid({
  files,
  outOfScopeFiles,
  renderCard,
  hasActiveFilter,
  activeDrag,
  existingSubgroups,
  canEditSubgroups,
  editingSubgroup,
  onEditingSubgroupChange,
  onRenameSubgroup,
  onClearSubgroup,
  vocab,
  onUpdateOutOfScope,
}: EditGroupFileGridProps) {
  const subgroups = subgroupOrder(files)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
      {subgroups.length > 1 ? (
        subgroups.map((subgroup) => {
          const sectionFiles = files.filter((f) => f.subgroup === subgroup)
          return (
            <DroppableSubgroupSection
              key={subgroup ?? '__main__'}
              subVariant={subgroup}
              activeDrag={activeDrag}
            >
              <SubgroupHeading
                subgroup={subgroup}
                count={sectionFiles.filter((f) => !f.excluded).length}
                isEditing={canEditSubgroups && subgroup !== null && editingSubgroup === subgroup}
                existingSubgroups={existingSubgroups}
                onStartEdit={() => onEditingSubgroupChange(subgroup)}
                onCommit={(val) => {
                  onRenameSubgroup(subgroup!, val)
                  onEditingSubgroupChange(null)
                }}
                onCancel={() => onEditingSubgroupChange(null)}
                onClear={() => onClearSubgroup(subgroup!)}
                canEdit={canEditSubgroups}
              />
              <div className="grid grid-cols-2 gap-2 pt-1.5 pb-2">
                {sectionFiles.map(renderCard)}
              </div>
            </DroppableSubgroupSection>
          )
        })
      ) : (
        <div className="grid grid-cols-2 gap-2">{files.map(renderCard)}</div>
      )}

      {files.length === 0 && hasActiveFilter && (
        <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
          <Search className="h-8 w-8 text-muted-foreground/30" />
          <p className="text-sm">No files match the current filter</p>
        </div>
      )}

      {outOfScopeFiles.length > 0 && (
        <div className="mt-4">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex-1 h-px bg-border/20" />
            <span className="text-[10px] font-semibold text-muted-foreground/40 uppercase tracking-wider whitespace-nowrap">
              Other images in this group
            </span>
            <div className="flex-1 h-px bg-border/20" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            {outOfScopeFiles.map((file) => (
              <FileCard
                key={file.relative_path}
                file={file}
                vocab={vocab}
                existingSubgroups={existingSubgroups}
                selected={false}
                onToggleSelect={() => {}}
                onUpdate={(updates) => onUpdateOutOfScope(file, updates)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
