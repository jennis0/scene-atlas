import { useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Search } from 'lucide-react'
import { FileCard } from '@/components/import/FileCard'
import { SubgroupHeading } from '@/components/SubgroupHeading'
import { DroppableSubgroupSection } from '@/components/import/shared/dnd'
import type { EditableFileState, ParsedTagVocab } from '@/types'
import { useEditGroupContext } from './EditGroupContext'
import { buildFileRows, type FileRow } from './fileRows'

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

/**
 * From this many files, only the rows on screen are rendered. Below it the grid renders
 * whole, keeping sticky subgroup headings and section-wide drop targets; above it, a
 * large import's All view would otherwise put every file card in the DOM.
 */
const VIRTUALIZE_FROM = 60

/** Rough heights until rows are measured: a file card row, and a subgroup heading. */
const CARD_ROW_ESTIMATE = 182
const HEADING_ROW_ESTIMATE = 36

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
  // State, not a ref: the rows' virtualiser needs the element on its first layout
  // effect, which runs before a parent's ref is attached
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null)

  return (
    <div ref={setScrollElement} className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
      <FileGridBody
        scrollElement={scrollElement}
        files={files}
        renderCard={renderCard}
        subgroups={subgroups}
      />

      {files.length === 0 && hasActiveFilter && (
        <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
          <Search className="h-8 w-8 text-muted-foreground" />
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

/** The cards: windowed for many files, else whole, in subgroup sections if there are several. */
function FileGridBody({
  scrollElement,
  files,
  renderCard,
  subgroups,
}: {
  scrollElement: HTMLDivElement | null
  files: EditableFileState[]
  renderCard: RenderCard
  subgroups: SubgroupEditing
}) {
  const order = subgroupOrder(files)
  if (files.length >= VIRTUALIZE_FROM) {
    return (
      <VirtualFileRows
        scrollElement={scrollElement}
        rows={buildFileRows(files, order)}
        renderCard={renderCard}
        editing={subgroups}
      />
    )
  }
  if (order.length <= 1) {
    return <div className="grid grid-cols-2 gap-2">{files.map(renderCard)}</div>
  }
  return order.map((subgroup) => (
    <SubgroupSection
      key={subgroup ?? '__main__'}
      subgroup={subgroup}
      files={files.filter((f) => f.subgroup === subgroup)}
      renderCard={renderCard}
      editing={subgroups}
    />
  ))
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
      <EditableSubgroupHeading subgroup={subgroup} files={files} editing={editing} />
      <div className="grid grid-cols-2 gap-2 pt-1.5 pb-2">{files.map(renderCard)}</div>
    </DroppableSubgroupSection>
  )
}

function EditableSubgroupHeading({
  subgroup,
  files,
  editing,
}: {
  subgroup: string | null
  files: EditableFileState[]
  editing: SubgroupEditing
}) {
  return (
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
  )
}

interface VirtualFileRowsProps {
  scrollElement: HTMLDivElement | null
  rows: FileRow[]
  renderCard: RenderCard
  editing: SubgroupEditing
}

/** The file grid, rendering only the rows near the viewport. */
function VirtualFileRows({ scrollElement, rows, renderCard, editing }: VirtualFileRowsProps) {
  const { activeDrag } = useEditGroupContext()
  const withHeadings = rows[0]?.kind === 'heading'
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollElement,
    estimateSize: (i) => (rows[i].kind === 'heading' ? HEADING_ROW_ESTIMATE : CARD_ROW_ESTIMATE),
    getItemKey: (i) => rows[i].key,
    overscan: 4,
  })

  return (
    <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
      {virtualizer.getVirtualItems().map((item) => {
        const row = rows[item.index]
        const content =
          row.kind === 'heading' ? (
            <EditableSubgroupHeading subgroup={row.subgroup} files={row.files} editing={editing} />
          ) : (
            <div className="grid grid-cols-2 gap-2 pb-2">{row.files.map(renderCard)}</div>
          )
        return (
          <div
            key={item.key}
            data-index={item.index}
            ref={virtualizer.measureElement}
            className="absolute left-0 top-0 w-full"
            style={{ transform: `translateY(${item.start}px)` }}
          >
            {withHeadings ? (
              // A drop target per row: rows mount and unmount as they scroll
              <DroppableSubgroupSection
                subVariant={row.subgroup}
                activeDrag={activeDrag}
                idSuffix={row.key}
              >
                {content}
              </DroppableSubgroupSection>
            ) : (
              content
            )}
          </div>
        )
      })}
    </div>
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
        <span className="text-xs font-semibold text-muted-foreground whitespace-nowrap">
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
