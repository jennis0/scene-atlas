import { Search } from 'lucide-react'
import { FileCard } from '@/components/import/FileCard'
import { SubgroupHeading } from '@/components/SubgroupHeading'
import { DroppableSubgroupSection } from '@/components/import/shared/dnd'
import type { EditableFileState, ParsedTagVocab } from '@/types'
import { useEditGroupContext } from './EditGroupContext'

/** Subgroup labels in scope, and the rename/clear controls for their headings. */
export interface SubgroupEditing {
  existing: string[]
  /** Headings can be renamed or cleared only when one group is shown. */
  canEdit: boolean
  editing: string | null
  setEditing: (subgroup: string | null) => void
  rename: (from: string, to: string) => void
  clear: (subgroup: string) => void
}

type RenderCard = (file: EditableFileState) => React.ReactNode

interface EditGroupFileGridProps {
  files: EditableFileState[]
  /** Images in the group but outside the edit scope, shown read-only for context. */
  outOfScopeFiles: EditableFileState[]
  renderCard: RenderCard
  hasActiveFilter: boolean
  subgroups: SubgroupEditing
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
  subgroups,
  vocab,
  onUpdateOutOfScope,
}: EditGroupFileGridProps) {
  const order = subgroupOrder(files)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
      {order.length > 1 ? (
        order.map((subgroup) => (
          <SubgroupSection
            key={subgroup ?? '__main__'}
            subgroup={subgroup}
            files={files.filter((f) => f.subgroup === subgroup)}
            renderCard={renderCard}
            editing={subgroups}
          />
        ))
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
        <OutOfScopeSection
          files={outOfScopeFiles}
          vocab={vocab}
          existingSubgroups={subgroups.existing}
          onUpdate={onUpdateOutOfScope}
        />
      )}
    </div>
  )
}

interface SubgroupSectionProps {
  subgroup: string | null
  files: EditableFileState[]
  renderCard: RenderCard
  editing: SubgroupEditing
}

function SubgroupSection({ subgroup, files, renderCard, editing }: SubgroupSectionProps) {
  const { activeDrag } = useEditGroupContext()

  return (
    <DroppableSubgroupSection subVariant={subgroup} activeDrag={activeDrag}>
      <SubgroupHeading
        subgroup={subgroup}
        count={files.filter((f) => !f.excluded).length}
        isEditing={editing.canEdit && subgroup !== null && editing.editing === subgroup}
        existingSubgroups={editing.existing}
        onStartEdit={() => editing.setEditing(subgroup)}
        onCommit={(val) => {
          editing.rename(subgroup!, val)
          editing.setEditing(null)
        }}
        onCancel={() => editing.setEditing(null)}
        onClear={() => editing.clear(subgroup!)}
        canEdit={editing.canEdit}
      />
      <div className="grid grid-cols-2 gap-2 pt-1.5 pb-2">{files.map(renderCard)}</div>
    </DroppableSubgroupSection>
  )
}

interface OutOfScopeSectionProps {
  files: EditableFileState[]
  vocab: ParsedTagVocab[]
  existingSubgroups: string[]
  onUpdate: (file: EditableFileState, updates: Partial<EditableFileState>) => void
}

function OutOfScopeSection({ files, vocab, existingSubgroups, onUpdate }: OutOfScopeSectionProps) {
  return (
    <div className="mt-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 h-px bg-border/20" />
        <span className="text-[10px] font-semibold text-muted-foreground/40 uppercase tracking-wider whitespace-nowrap">
          Other images in this group
        </span>
        <div className="flex-1 h-px bg-border/20" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        {files.map((file) => (
          <FileCard
            key={file.relative_path}
            file={file}
            vocab={vocab}
            existingSubgroups={existingSubgroups}
            selected={false}
            onToggleSelect={() => {}}
            onUpdate={(updates) => onUpdate(file, updates)}
          />
        ))}
      </div>
    </div>
  )
}
