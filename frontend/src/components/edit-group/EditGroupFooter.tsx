import { AlertCircle, Check, Loader2, Merge, Trash2 } from 'lucide-react'
import { useEditGroupContext } from './EditGroupContext'

interface EditGroupFooterProps {
  /** Delete and merge are offered only for the persisted group opened in single-group mode. */
  showGroupActions: boolean
  onDone: () => void
  /** Import review makes Done the primary button. */
  primaryDone: boolean
}

export function EditGroupFooter({ showGroupActions, onDone, primaryDone }: EditGroupFooterProps) {
  return (
    <div className="px-5 py-3 border-t border-border/30 shrink-0 flex items-center justify-between gap-3">
      {showGroupActions ? <GroupActions /> : <div />}
      <div className="flex items-center gap-2">
        <SaveStatus />
        <DoneButton onDone={onDone} primary={primaryDone} />
      </div>
    </div>
  )
}

/** Delete Group / Merge into…, or the inline delete confirmation. */
function GroupActions() {
  const { pending, setPending, ops } = useEditGroupContext()

  if (pending?.kind === 'deleteGroup') {
    const button = 'px-2.5 py-1 text-xs rounded border transition-colors disabled:opacity-50'
    return (
      <div className="flex items-center gap-2 text-sm text-destructive">
        <span>Delete this group and all its images?</span>
        <button
          onClick={async () => {
            if (!(await ops.handleDelete())) setPending(null)
          }}
          disabled={ops.saving}
          className={`${button} border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/20`}
        >
          {ops.saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Confirm'}
        </button>
        <button
          onClick={() => setPending(null)}
          disabled={ops.saving}
          className={`${button} border-border bg-secondary text-muted-foreground hover:text-foreground`}
        >
          Cancel
        </button>
      </div>
    )
  }

  const button = 'flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded transition-colors'
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => setPending({ kind: 'deleteGroup' })}
        className={`${button} text-destructive/70 hover:text-destructive hover:bg-destructive/10`}
      >
        <Trash2 className="h-3.5 w-3.5" />
        Delete Group
      </button>
      <button
        onClick={() => setPending({ kind: 'mergeInto', sourceId: null })}
        disabled={ops.saving || ops.merging}
        className={`${button} text-muted-foreground hover:text-foreground hover:bg-secondary disabled:opacity-50`}
      >
        <Merge className="h-3.5 w-3.5" />
        Merge into…
      </button>
    </div>
  )
}

/** The save error, else auto-save progress, else "Saved" once anything has saved. */
function SaveStatus() {
  const { ops } = useEditGroupContext()

  if (ops.saveError) {
    return (
      <span className="text-xs text-destructive flex items-center gap-1 max-w-xs truncate">
        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
        {ops.saveError}
      </span>
    )
  }
  if (ops.groupSaving.size > 0) {
    return (
      <span className="text-xs text-muted-foreground flex items-center gap-1">
        <Loader2 className="h-3 w-3 animate-spin" />
        Saving…
      </span>
    )
  }
  if (ops.groupSaved.size > 0) {
    return (
      <span className="text-xs text-success flex items-center gap-1">
        <Check className="h-3 w-3" />
        Saved
      </span>
    )
  }
  return null
}

function DoneButton({ onDone, primary }: { onDone: () => void; primary: boolean }) {
  const { ops } = useEditGroupContext()
  const busy = ops.saving || ops.groupSaving.size > 0

  return (
    <button
      onClick={onDone}
      disabled={busy}
      className={
        primary
          ? 'px-4 py-1.5 text-sm rounded font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40'
          : 'px-3 py-1.5 text-sm rounded border border-primary/40 bg-primary/10 text-primary hover:bg-primary/30 transition-colors disabled:opacity-40'
      }
    >
      {busy ? (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />
          {ops.saving ? 'Working…' : 'Saving…'}
        </>
      ) : (
        'Done'
      )}
    </button>
  )
}
