import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import type { useBulkImageEdit } from '@/hooks/useBulkImageEdit'

/** Asks before a bulk edit over many images runs. */
export function BulkEditConfirm({ bulk }: { bulk: ReturnType<typeof useBulkImageEdit> }) {
  return (
    <ConfirmDialog
      open={bulk.pending !== null}
      onOpenChange={(open) => !open && bulk.cancel()}
      title="Edit many images?"
      description={bulk.pending ? `${bulk.describe(bulk.pending)} You can undo it afterwards.` : ''}
      confirmLabel="Apply"
      confirmVariant="default"
      onConfirm={bulk.confirm}
    />
  )
}
