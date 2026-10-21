import { RotateCcw } from 'lucide-react'

export interface RestartPromptProps {
  /** The setting has changed, and the change waits for a restart */
  pending: boolean
  /** Restart now. Absent where the app can't restart itself (a server). */
  onRestart?: () => void
  /** A restart can't apply the change yet (the new folders are still being checked) */
  disabled?: boolean
  restarting?: boolean
}

const BADGE =
  'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold bg-warning/10 text-warning border border-warning/30'

/** For a setting that applies only after a restart: a quiet note until it changes, then
 * a button that restarts to apply it (on a server, which can't restart itself, a label). */
export function RestartBadge({ pending, onRestart, disabled, restarting }: RestartPromptProps) {
  if (!pending) {
    return <p className="text-xs text-muted-foreground">Applies after a restart</p>
  }
  if (!onRestart) {
    return (
      <span className={BADGE}>
        <RotateCcw className="size-2.5" aria-hidden />
        Restart the server to apply
      </span>
    )
  }
  return (
    <button
      type="button"
      onClick={onRestart}
      disabled={disabled || restarting}
      className={`${BADGE} hover:bg-warning/20 disabled:opacity-50 disabled:hover:bg-warning/10`}
    >
      <RotateCcw className="size-2.5" aria-hidden />
      {restarting ? 'Restarting…' : 'Restart to apply'}
    </button>
  )
}
