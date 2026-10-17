import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { MergeGroupPicker } from '@/components/MergeGroupPicker'
import type { EditableGroupState } from '@/types'
import { useEditGroupContext } from './EditGroupContext'

export interface DragMerge {
  sourceIds: string[] | null
  target: string | null
  clear: () => void
}

interface EditGroupConfirmDialogsProps {
  groupId?: number | null
  activeGroup: EditableGroupState | undefined
  dragMerge: DragMerge
}

function groupNameIn(groups: EditableGroupState[], id: string | null | undefined): string {
  return groups.find((g) => g.id === id)?.group_name ?? ''
}

/** The merge picker and the modal confirmations of the edit dialog. */
export function EditGroupConfirmDialogs({
  groupId,
  activeGroup,
  dragMerge,
}: EditGroupConfirmDialogsProps) {
  return (
    <>
      <MergePicker groupId={groupId} activeGroup={activeGroup} />
      <MergeAllConfirm />
      <DragMergeConfirm dragMerge={dragMerge} />
      <BulkMergeConfirm />
      <BulkDeleteConfirm />
    </>
  )
}

/** "Merge into…" for a sidebar row (sourceId set) or the dialog's own group. */
function MergePicker({
  groupId,
  activeGroup,
}: Pick<EditGroupConfirmDialogsProps, 'groupId' | 'activeGroup'>) {
  const { groups, pending, setPending, ops } = useEditGroupContext()
  const sourceId = pending?.kind === 'mergeInto' ? pending.sourceId : null

  return (
    <MergeGroupPicker
      open={pending?.kind === 'mergeInto'}
      onClose={() => setPending(null)}
      excludeGroupId={sourceId !== null ? Number(sourceId) : groupId}
      onSelect={async (target) => {
        const merged = sourceId
          ? await ops.handleMergeGroup(sourceId, target)
          : await ops.handleMerge(target)
        if (merged) setPending(null)
      }}
      currentGroupName={sourceId !== null ? groupNameIn(groups, sourceId) : activeGroup?.group_name}
    />
  )
}

function MergeAllConfirm() {
  const { groups, pending, setPending, ops } = useEditGroupContext()

  return (
    <ConfirmDialog
      open={pending?.kind === 'mergeAll'}
      onOpenChange={(open) => !open && setPending(null)}
      title="Merge All Groups"
      description={`This will merge all ${groups.length} groups into "${groups[0]?.group_name ?? ''}". This cannot be undone.`}
      confirmLabel="Merge All"
      confirmVariant="default"
      loadingLabel="Merging…"
      onConfirm={() => {
        setPending(null)
        ops.handleMergeAll()
      }}
      isLoading={ops.merging}
    />
  )
}

function dragMergeDescription(groups: EditableGroupState[], sourceIds: string[], target: string) {
  const targetName = groupNameIn(groups, target)
  if (sourceIds.length > 1) {
    return `Merge ${sourceIds.length} groups into "${targetName}"? This cannot be undone.`
  }
  const source = groups.find((g) => g.id === sourceIds[0])
  const images = source?.files.filter((f) => !f.excluded).length ?? 0
  return `Merge "${source?.group_name ?? ''}" (${images} images) into "${targetName}"? This cannot be undone.`
}

/** Confirms dropping one or more sidebar groups onto another. */
function DragMergeConfirm({ dragMerge }: { dragMerge: DragMerge }) {
  const { groups, clearSelection, ops } = useEditGroupContext()
  const { sourceIds, target } = dragMerge
  const isMulti = (sourceIds?.length ?? 0) > 1

  return (
    <ConfirmDialog
      open={sourceIds !== null && target !== null}
      onOpenChange={(open) => !open && dragMerge.clear()}
      title="Merge Groups"
      description={sourceIds && target ? dragMergeDescription(groups, sourceIds, target) : ''}
      confirmLabel={isMulti ? `Merge ${sourceIds!.length} Groups` : 'Merge'}
      confirmVariant="default"
      loadingLabel="Merging…"
      onConfirm={() => {
        if (sourceIds && target) {
          ops.handleDragMergeConfirm(sourceIds, target).then(() => {
            dragMerge.clear()
            clearSelection()
          })
        }
      }}
      isLoading={ops.merging}
    />
  )
}

function BulkMergeConfirm() {
  const { groups, selectedGroupIds, clearSelection, pending, setPending, ops } =
    useEditGroupContext()

  return (
    <ConfirmDialog
      open={pending?.kind === 'bulkMerge'}
      onOpenChange={(open) => !open && setPending(null)}
      title="Merge Selected Groups"
      description={`This will merge ${selectedGroupIds.size} selected groups into "${groupNameIn(groups, [...selectedGroupIds][0])}". This cannot be undone.`}
      confirmLabel="Merge Selected"
      confirmVariant="default"
      loadingLabel="Merging…"
      onConfirm={() => {
        setPending(null)
        ops.handleBulkMerge(selectedGroupIds).then(clearSelection)
      }}
      isLoading={ops.merging}
    />
  )
}

function BulkDeleteConfirm() {
  const { selectedGroupIds, clearSelection, pending, setPending, ops } = useEditGroupContext()

  return (
    <ConfirmDialog
      open={pending?.kind === 'bulkDelete'}
      onOpenChange={(open) => !open && setPending(null)}
      title="Delete Selected Groups"
      description={`This will permanently delete ${selectedGroupIds.size} groups and all their images. This cannot be undone.`}
      confirmLabel="Delete All"
      confirmVariant="destructive"
      loadingLabel="Deleting…"
      onConfirm={() => {
        setPending(null)
        ops.handleBulkDelete(selectedGroupIds).then(clearSelection)
      }}
      isLoading={ops.saving}
    />
  )
}
