/** The one confirmation (inline, modal or picker) the edit dialog is showing, if any. */
export type PendingConfirm =
  | { kind: 'deleteGroup' }
  /** sourceId null: merge the dialog's own group (single-group mode). */
  | { kind: 'mergeInto'; sourceId: string | null }
  | { kind: 'deleteRow'; groupId: string }
  | { kind: 'mergeAll' }
  | { kind: 'bulkMerge' }
  | { kind: 'bulkDelete' }

export type SetPendingConfirm = (confirm: PendingConfirm | null) => void
