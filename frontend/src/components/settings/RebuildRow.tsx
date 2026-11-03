/**
 * Settings → Library → Rebuild from export (design/export-backup-move.md §8). Replaces the
 * library's metadata with a metadata export: upload it, see what would change (images in
 * it whose files are missing, images in the library it doesn't have), rebuild, restart.
 * The live library is untouched until the restart; files the export doesn't know are set
 * aside in a folder afterwards, not deleted.
 */

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { libraryApi, type RebuildCheck, type RebuildListed } from '@/lib/api/libraryApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { useJobPolling } from '@/hooks/useJobPolling'

const STATUS_KEY = ['rebuild'] as const

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`
}

export function RebuildRow() {
  const queryClient = useQueryClient()
  const job = useJobPolling()
  const input = useRef<HTMLInputElement>(null)
  const [uploaded, setUploaded] = useState<number | null>(null)
  const [restarting, setRestarting] = useState<string | null>(null)
  const status = useQuery({ queryKey: STATUS_KEY, queryFn: libraryApi.rebuildStatus })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: STATUS_KEY })

  const runningId = status.data?.job_id ?? null
  const { track, isComplete, isFailed } = job
  useEffect(() => {
    if (runningId) track(runningId)
  }, [runningId, track])
  useEffect(() => {
    if (isComplete || isFailed) refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isComplete, isFailed])

  const onError = (fallback: string) => (err: unknown) => {
    toast.error(getApiErrorMessage(err, fallback))
    refresh()
  }

  const upload = useMutation({
    mutationFn: async (file: File) => {
      setUploaded(0)
      await libraryApi.uploadRebuild(file, setUploaded)
      return libraryApi.checkRebuild()
    },
    onSuccess: (data) => job.track(data.job_id),
    onError: onError('Could not upload the export'),
    onSettled: () => {
      setUploaded(null)
      refresh()
    },
  })
  const build = useMutation({
    mutationFn: libraryApi.buildRebuild,
    onSuccess: (data) => job.track(data.job_id),
    onError: onError('Could not start the rebuild'),
  })
  const cancel = useMutation({
    mutationFn: libraryApi.cancelRebuild,
    onError: onError('Could not cancel the rebuild'),
    onSettled: refresh,
  })
  const dismiss = useMutation({
    mutationFn: libraryApi.dismissRebuildSummary,
    onError: onError('Could not dismiss that'),
    onSettled: refresh,
  })
  const apply = useMutation({
    mutationFn: libraryApi.applyRebuild,
    onSuccess: async ({ restart }) => {
      if (restart === 'server') {
        setRestarting('The server is restarting into the rebuilt library…')
        waitForServer(() => setRestarting(SERVER_NOT_BACK))
        return
      }
      setRestarting('Restarting into the rebuilt library…')
      // Resolves only when the app can't restart its backend (dev); otherwise it reloads
      if (!(await window.electronAPI?.restartBackend())) {
        setRestarting('Restart Scene Atlas to finish the rebuild.')
      }
    },
    onError: onError('Could not apply the rebuild'),
  })

  const data = status.data
  const busy = job.isRunning || upload.isPending || build.isPending
  const check = data?.check ?? null

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-foreground/90 hc:text-foreground">Rebuild from export</p>
          <p className="text-xs text-muted-foreground">
            Replace this library&apos;s names, groups, tags and search data with a metadata export.
          </p>
        </div>
        {busy ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>
              {uploaded !== null
                ? `Uploading… ${(uploaded / 1024 ** 2).toFixed(0)} MB`
                : (job.progress ?? 'Working…')}
            </span>
          </div>
        ) : (
          !check &&
          !data?.built && (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => input.current?.click()}
              className="gap-1.5 h-7 text-xs shrink-0"
            >
              <History className="h-3 w-3" />
              Rebuild…
            </Button>
          )
        )}
        <input
          ref={input}
          type="file"
          accept=".gz,.jsonl,application/gzip"
          className="hidden"
          aria-label="Metadata export to rebuild from"
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) upload.mutate(file)
          }}
        />
      </div>

      {(job.isFailed || (data?.check_error && !check)) && !busy && (
        <div className="space-y-1.5">
          <p className="text-xs text-destructive" role="alert">
            {job.error ?? data?.check_error ?? 'That failed.'} Nothing in your library has changed.
          </p>
          {data?.staged && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => cancel.mutate()}
            >
              Forget that export
            </Button>
          )}
        </div>
      )}

      {restarting ? (
        <p className="text-xs text-muted-foreground" role="status">
          {restarting}
        </p>
      ) : data?.built && !busy ? (
        <div className="rounded-md border border-border/60 p-2.5 space-y-2" role="status">
          <p className="text-xs">
            The rebuilt library is ready. Scene Atlas restarts to put it in place. Changes made from
            now on won&apos;t be in it.
          </p>
          <div className="flex gap-2">
            <Button size="sm" className="h-7 text-xs" onClick={() => apply.mutate()}>
              Restart now
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => cancel.mutate()}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        check &&
        !busy && (
          <CheckReport
            check={check}
            onRebuild={() => build.mutate()}
            onCancel={() => cancel.mutate()}
          />
        )
      )}

      {data?.summary && !check && !data.built && (
        <p className="text-xs text-muted-foreground" role="status">
          <button
            type="button"
            className="float-right ml-2 underline"
            onClick={() => dismiss.mutate()}
          >
            Dismiss
          </button>
          Rebuilt.{' '}
          {data.summary.moved > 0 && data.summary.folder
            ? `${plural(data.summary.moved, 'file')} the export didn't have ${
                data.summary.moved === 1 ? 'is' : 'are'
              } in ${data.summary.folder}: import that folder to bring them back.`
            : 'Every file in the library was in the export.'}
          {!!data.summary.not_moved?.length &&
            ` ${plural(data.summary.not_moved.length, 'file')} couldn't be moved and ${
              data.summary.not_moved.length === 1 ? 'is' : 'are'
            } still in the library's folder (see the log).`}
        </p>
      )}
      {data?.set_aside_running && (
        <p className="text-xs text-muted-foreground">
          Setting aside the files the export didn&apos;t have…
        </p>
      )}
    </div>
  )
}

const SERVER_NOT_BACK =
  "The server hasn't come back. If it isn't run by a service manager (such as Docker " +
  "Compose's restart policy), start it again: the rebuild finishes as it starts."

/** Reload once the server answers again; *gaveUp* after two minutes. */
function waitForServer(gaveUp: () => void) {
  const started = Date.now()
  const poll = async () => {
    try {
      const response = await fetch('/health', { cache: 'no-store' })
      if (response.ok && Date.now() - started > 3000) {
        window.location.reload()
        return
      }
    } catch {
      // still down
    }
    if (Date.now() - started > 120_000) gaveUp()
    else setTimeout(poll, 2000)
  }
  setTimeout(poll, 3000)
}

function CheckReport({
  check,
  onRebuild,
  onCancel,
}: {
  check: RebuildCheck
  onRebuild: () => void
  onCancel: () => void
}) {
  const nothing = check.missing.images === 0 && check.lost.images === 0
  return (
    <div className="rounded-md border border-border/60 p-2.5 space-y-2 text-xs">
      <p>
        The export has {plural(check.images, 'image')} in {plural(check.groups, 'group')}, from{' '}
        {new Date(check.created_at).toLocaleString()}.
      </p>
      {check.different_library && (
        <p className="text-destructive">This export is from a different library.</p>
      )}
      {nothing && <p>Nothing is missing, and nothing in your library will be lost.</p>}
      <Listed
        listed={check.missing}
        sentence={(images, groups) => `${images} in ${groups} are missing.`}
        detail="Their files aren't in this library, so they won't be in the rebuilt one."
      />
      <Listed
        listed={check.lost}
        sentence={(images, groups) =>
          `${images} in ${groups} in your current library will be lost.`
        }
        detail="They aren't in the export. Their files are set aside in a folder you can import again."
      />
      {check.linked_missing > 0 && (
        <p className="text-muted-foreground">
          {plural(check.linked_missing, 'linked image')} in the export aren&apos;t in the linked
          library now. They&apos;re kept, and shown as missing.
        </p>
      )}
      {check.linked_lost > 0 && (
        <p className="text-muted-foreground">
          {plural(check.linked_lost, 'linked image')} in your library aren&apos;t in the export.
          Their files stay in the linked library, which adds them again, without their names, tags
          and groups.
        </p>
      )}
      {!check.linked_checked && (
        <p className="text-muted-foreground">
          The linked library isn&apos;t connected, so its files weren&apos;t checked.
        </p>
      )}
      {check.reembed && (
        <p className="text-muted-foreground">
          The export&apos;s search data is from another model, so images are processed again
          afterwards. That takes a while for a large library.
        </p>
      )}
      <div className="flex gap-2 pt-1">
        <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={onRebuild}>
          Rebuild
        </Button>
        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function Listed({
  listed,
  sentence,
  detail,
}: {
  listed: RebuildListed
  sentence: (images: string, groups: string) => string
  detail: string
}) {
  if (listed.images === 0) return null
  const more = listed.group_count - listed.groups.length
  return (
    <details>
      <summary className="cursor-pointer font-medium">
        {sentence(plural(listed.images, 'image'), plural(listed.group_count, 'group'))}
      </summary>
      <p className="mt-1 text-muted-foreground">{detail}</p>
      <ul className="mt-1 ml-4 space-y-0.5">
        {listed.groups.map((g, n) => (
          <li key={`${g.name}-${n}`}>
            <details>
              <summary className="cursor-pointer">
                {g.name} ({g.images.length})
              </summary>
              <ul className="ml-4 list-disc text-muted-foreground">
                {g.images.map((name, i) => (
                  <li key={`${name}-${i}`} className="break-all">
                    {name}
                  </li>
                ))}
              </ul>
            </details>
          </li>
        ))}
        {more > 0 && <li className="text-muted-foreground">and {plural(more, 'more group')}</li>}
      </ul>
    </details>
  )
}
