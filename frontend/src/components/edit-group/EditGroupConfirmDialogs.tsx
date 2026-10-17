import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { MergeGroupPicker } from '@/components/MergeGroupPicker'
import type { UseEditGroupOperationsReturn } from '@/hooks/useEditGroupOperations'
import type { EditableGroupState } from '@/types'
import type { PendingConfirm, SetPendingConfirm } from './pendingConfirm'

interface DragMerge {
  sourceIds: string[] | null
  target: string | null
  clear: () => void
}

interface EditGroupConfirmDialogsProps {
  groupId?: number | null
  groups: EditableGroupState[]
  activeGroup: EditableGroupState | undefined
  selectedGroupIds: Set<string>
  clearSelection: () => void
  pending: PendingConfirm | null
  setPending: SetPendingConfirm
  dragMerge: DragMerge
  ops: UseEditGroupOperationsReturn
}

/** The merge picker and the modal confirmations of the edit dialog. */
export function EditGroupConfirmDialogs({
  groupId,
  groups,
  activeGroup,
  selectedGroupIds,
  clearSelection,
  pending,
  setPending,
  dragMerge,
  ops,
}: EditGroupConfirmDialogsProps) {
  const groupName = (id: string | null | undefined) =>
    groups.find((g) => g.id === id)?.group_name ?? ''
  const closeOn = (open: boolean) => !open && setPending(null)

  const mergeSourceId = pending?.kind === 'mergeInto' ? pending.sourceId : null
  const [dragSource] = dragMerge.sourceIds ?? []
  const isMultiDrag = (dragMerge.sourceIds?.length ?? 0) > 1

  return (
    <>
      <MergeGroupPicker
        open={pending?.kind === 'mergeInto'}
        onClose={() => setPending(null)}
        excludeGroupId={mergeSourceId !== null ? Number(mergeSourceId) : groupId}
        onSelect={async (target) => {
          const merged = mergeSourceId
            ? await ops.handleMergeGroup(mergeSourceId, target)
            : await ops.handleMerge(target)
          if (merged) setPending(null)
        }}
        currentGroupName={
          mergeSourceId !== null ? groupName(mergeSourceId) : activeGroup?.group_name
        }
      />

      <ConfirmDialog
        open={pending?.kind === 'mergeAll'}
        onOpenChange={closeOn}
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

      <ConfirmDialog
        open={dragMerge.sourceIds !== null && dragMerge.target !== null}
        onOpenChange={(open) => !open && dragMerge.clear()}
        title="Merge Groups"
        description={
          isMultiDrag
            ? `Merge ${dragMerge.sourceIds!.length} groups into "${groupName(dragMerge.target)}"? This cannot be undone.`
            : `Merge "${groupName(dragSource)}" (${groups.find((g) => g.id === dragSource)?.files.filter((f) => !f.excluded).length ?? 0} images) into "${groupName(dragMerge.target)}"? This cannot be undone.`
        }
        confirmLabel={isMultiDrag ? `Merge ${dragMerge.sourceIds!.length} Groups` : 'Merge'}
        confirmVariant="default"
        loadingLabel="Merging…"
        onConfirm={() => {
          if (dragMerge.sourceIds && dragMerge.target) {
            ops.handleDragMergeConfirm(dragMerge.sourceIds, dragMerge.target).then(() => {
              dragMerge.clear()
              clearSelection()
            })
          }
        }}
        isLoading={ops.merging}
      />

      <ConfirmDialog
        open={pending?.kind === 'bulkMerge'}
        onOpenChange={closeOn}
        title="Merge Selected Groups"
        description={`This will merge ${selectedGroupIds.size} selected groups into "${groupName([...selectedGroupIds][0])}". This cannot be undone.`}
        confirmLabel="Merge Selected"
        confirmVariant="default"
        loadingLabel="Merging…"
        onConfirm={() => {
          setPending(null)
          ops.handleBulkMerge(selectedGroupIds).then(clearSelection)
        }}
        isLoading={ops.merging}
      />

      <ConfirmDialog
        open={pending?.kind === 'bulkDelete'}
        onOpenChange={closeOn}
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
    </>
  )
}
