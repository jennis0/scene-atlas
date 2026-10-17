import { AlertCircle, Check, Loader2, Merge, Trash2 } from 'lucide-react'
import type { PendingConfirm, SetPendingConfirm } from './pendingConfirm'

interface EditGroupFooterProps {
  /** Delete and merge are offered only for the persisted group opened in single-group mode. */
  showGroupActions: boolean
  pending: PendingConfirm | null
  setPending: SetPendingConfirm
  onDelete: () => void
  onDone: () => void
  saving: boolean
  merging: boolean
  saveError: string | null
  groupSaving: Set<string>
  groupSaved: Set<string>
  primaryDone: boolean
}

export function EditGroupFooter({
  showGroupActions,
  pending,
  setPending,
  onDelete,
  onDone,
  saving,
  merging,
  saveError,
  groupSaving,
  groupSaved,
  primaryDone,
}: EditGroupFooterProps) {
  const autoSaving = groupSaving.size > 0
  const confirmButton = 'px-2.5 py-1 text-xs rounded border transition-colors disabled:opacity-50'
  const actionButton = 'flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded transition-colors'

  return (
    <div className="px-5 py-3 border-t border-border/30 shrink-0 flex items-center justify-between gap-3">
      {!showGroupActions ? (
        <div />
      ) : pending?.kind === 'deleteGroup' ? (
        <div className="flex items-center gap-2 text-sm text-destructive">
          <span>Delete this group and all its images?</span>
          <button
            onClick={onDelete}
            disabled={saving}
            className={`${confirmButton} border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/20`}
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Confirm'}
          </button>
          <button
            onClick={() => setPending(null)}
            disabled={saving}
            className={`${confirmButton} border-border bg-secondary text-muted-foreground hover:text-foreground`}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPending({ kind: 'deleteGroup' })}
            className={`${actionButton} text-destructive/70 hover:text-destructive hover:bg-destructive/10`}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete Group
          </button>
          <button
            onClick={() => setPending({ kind: 'mergeInto', sourceId: null })}
            disabled={saving || merging}
            className={`${actionButton} text-muted-foreground hover:text-foreground hover:bg-secondary disabled:opacity-50`}
          >
            <Merge className="h-3.5 w-3.5" />
            Merge into…
          </button>
        </div>
      )}

      <div className="flex items-center gap-2">
        {saveError && (
          <span className="text-xs text-destructive flex items-center gap-1 max-w-xs truncate">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {saveError}
          </span>
        )}
        {!saveError && autoSaving && (
          <span className="text-xs text-muted-foreground/60 flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            Saving…
          </span>
        )}
        {!saveError && !autoSaving && groupSaved.size > 0 && (
          <span className="text-xs text-emerald-600 dark:text-emerald-400/70 flex items-center gap-1">
            <Check className="h-3 w-3" />
            Saved
          </span>
        )}
        <button
          onClick={onDone}
          disabled={saving || autoSaving}
          className={
            primaryDone
              ? 'px-4 py-1.5 text-sm rounded font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40'
              : 'px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40'
          }
        >
          {saving || autoSaving ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
              {saving ? 'Working…' : 'Saving…'}
            </>
          ) : (
            'Done'
          )}
        </button>
      </div>
    </div>
  )
}
