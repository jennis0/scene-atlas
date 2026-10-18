/**
 * The import dialog (ADR-018; screens in design/frontend.md "Imports", client
 * sequence in design/ingestion.md §8.1).
 *
 * Three views over the ImportManager, in one frame:
 * - Start: choose battlemap/scene, then drop or browse files, folders or zips.
 * - Progress: what's being sent and imported, any problems, the group ledger,
 *   and controls. Closing never stops anything; reopening shows the same job.
 * - Result (ImportResultView): once the job finishes the dialog turns into what
 *   the import did, with Review in editor, Undo import and Done.
 */

import { useRef, useState } from 'react'
import {
  AlertTriangle,
  Ban,
  FileWarning,
  Files,
  FolderOpen,
  Grid3X3,
  Image as ImageIcon,
  Loader2,
  Pause,
  PauseCircle,
  Play,
  Wand2,
  UploadCloud,
  WifiOff,
} from 'lucide-react'
import { toast } from 'sonner'
import { getImportManager } from '@/lib/import/ImportManager'
import { useImportJob, useImportManagerSnapshot } from '@/lib/import/useImports'
import type { ImageType, PickedFile } from '@/lib/import/types'
import { ConfirmOverlay, ImportFrame, Notice, TextButton } from './ImportFrame'
import { NowImporting, ProblemsLine, ProgressSummary } from './ImportProgress'
import { ResultView } from './ImportResultView'
import {
  formatBytes,
  isFinished,
  jobStatusText,
  outcomeText,
  plural,
  uploadPhaseText,
} from './format'
import { filesFromDrop, filesFromInput } from './pickFiles'
import { canImportLocally, chooseLocalPaths, pathsFromDrop } from '@/lib/import/localPaths'

interface ImportDialogProps {
  /** null: start a new import. Otherwise show that job. */
  jobId: string | null
  open: boolean
  onClose: () => void
  /** A new import was created; the parent should now show it. */
  onStarted: (jobId: string) => void
  /** Open the import's groups in the group editor, optionally on one of them. */
  onReviewGroups?: (imageGroupIds: number[], startGroupId?: number) => void
  /** The import was undone (its images deleted). */
  onUndone?: () => void
}

export function ImportDialog({
  jobId,
  open,
  onClose,
  onStarted,
  onReviewGroups,
  onUndone,
}: ImportDialogProps) {
  const { job } = useImportJob(jobId)
  if (!jobId) return <StartView open={open} onClose={onClose} onStarted={onStarted} />
  if (job && isFinished(job)) {
    return (
      <ResultView
        jobId={jobId}
        open={open}
        onClose={onClose}
        onReviewGroups={onReviewGroups}
        onUndone={onUndone}
      />
    )
  }
  return (
    <ProgressView jobId={jobId} open={open} onClose={onClose} onReviewGroups={onReviewGroups} />
  )
}

// Start

function StartView({
  open,
  onClose,
  onStarted,
}: {
  open: boolean
  onClose: () => void
  onStarted: (jobId: string) => void
}) {
  const [imageType, setImageType] = useState<ImageType>('auto')
  const [reading, setReading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)
  const busy = reading || starting

  const begin = async (launch: () => Promise<string>) => {
    setStarting(true)
    try {
      const jobId = await launch()
      onStarted(jobId)
    } catch {
      toast.error("Couldn't start the import", {
        description: 'The server could not be reached. Check that Scene Atlas is running.',
      })
    } finally {
      setStarting(false)
    }
  }

  const start = async (files: PickedFile[]) => {
    if (files.length) await begin(() => getImportManager().startImport(files, { imageType }))
  }

  // Desktop app: the server reads the files where they are (design/local-ingest.md)
  const startLocal = async (paths: string[]) => {
    if (paths.length) await begin(() => getImportManager().startLocalImport(paths, { imageType }))
  }

  const local = canImportLocally()
  const choose = (kind: 'folders' | 'files') => {
    if (local) {
      void chooseLocalPaths(kind).then(startLocal)
      return
    }
    const input = kind === 'folders' ? folderInput.current : fileInput.current
    input?.click()
  }

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (busy) return
    const paths = pathsFromDrop(e.dataTransfer)
    if (paths) {
      await startLocal(paths)
      return
    }
    setReading(true)
    const files = await filesFromDrop(e.dataTransfer).finally(() => setReading(false))
    await start(files)
  }

  return (
    <ImportFrame open={open} onClose={onClose} title="Import maps and scenes">
      <div className="px-6 pt-2 pb-6 space-y-5">
        <fieldset className="space-y-2" disabled={busy}>
          <legend className="text-xs text-muted-foreground mb-2">Import these as</legend>
          <div className="inline-flex rounded-md overflow-hidden border border-border">
            <TypeOption
              selected={imageType === 'auto'}
              onClick={() => setImageType('auto')}
              icon={<Wand2 className="h-3.5 w-3.5" />}
              label="Auto"
            />
            <TypeOption
              selected={imageType === 'battlemap'}
              onClick={() => setImageType('battlemap')}
              icon={<Grid3X3 className="h-3.5 w-3.5" />}
              label="Battlemaps"
            />
            <TypeOption
              selected={imageType === 'scene'}
              onClick={() => setImageType('scene')}
              icon={<ImageIcon className="h-3.5 w-3.5" />}
              label="Scenes"
            />
          </div>
          <p className="text-xs text-muted-foreground">{TYPE_HINT[imageType]}</p>
        </fieldset>

        <input
          ref={fileInput}
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.webp,.mp4,.webm,.zip"
          className="hidden"
          onChange={(e) => void start(filesFromInput(e.target.files))}
        />
        <input
          ref={folderInput}
          type="file"
          // @ts-expect-error webkitdirectory is not in the HTMLInputElement type
          webkitdirectory=""
          multiple
          className="hidden"
          onChange={(e) => void start(filesFromInput(e.target.files))}
        />

        <div
          onDragOver={(e) => {
            e.preventDefault()
            if (!busy) setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => void onDrop(e)}
          className={`flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 transition-colors ${
            busy
              ? 'border-border/40 bg-secondary/20'
              : dragOver
                ? 'border-primary bg-primary/[0.06]'
                : 'border-border/60'
          }`}
        >
          {busy ? (
            <>
              <Loader2 className="h-8 w-8 animate-spin text-primary/70 hc:text-primary" />
              <p className="text-xs text-muted-foreground">
                {reading ? 'Reading the dropped folders' : 'Starting the import'}
              </p>
            </>
          ) : (
            <>
              <UploadCloud
                className={`h-9 w-9 ${dragOver ? 'text-primary' : 'text-muted-foreground'}`}
              />
              <div className="text-center">
                <p
                  className={`text-sm font-medium ${dragOver ? 'text-primary' : 'text-foreground'}`}
                >
                  {dragOver ? 'Drop to import' : 'Drop files or folders here'}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Images, videos and .zip archives. Folder names become groups.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <BrowseButton
                  onClick={() => choose('folders')}
                  icon={<FolderOpen className="h-3.5 w-3.5" />}
                  label="Choose a folder"
                />
                <BrowseButton
                  onClick={() => choose('files')}
                  icon={<Files className="h-3.5 w-3.5" />}
                  label="Choose files"
                />
              </div>
            </>
          )}
        </div>
      </div>
    </ImportFrame>
  )
}

const TYPE_HINT: Record<ImageType, string> = {
  auto: 'Sorts each image into battlemaps and scenes. Tokens and other art are skipped for you to check.',
  battlemap: 'Top-down maps. Grids are detected automatically.',
  scene: 'Vistas, portraits and encounter art. No grid detection.',
}

function TypeOption({
  selected,
  onClick,
  icon,
  label,
}: {
  selected: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 h-8 px-3 text-xs transition-colors focus-visible:outline-offset-[-2px] border-r border-border last:border-r-0 ${
        selected
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}

function BrowseButton({
  onClick,
  icon,
  label,
}: {
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 h-8 px-3 text-xs rounded-md border border-border/60 bg-secondary/60 text-muted-foreground hover:text-foreground hover:border-border hover:bg-secondary transition-colors"
    >
      {icon}
      {label}
    </button>
  )
}

// Progress

function ProgressView({
  jobId,
  open,
  onClose,
  onReviewGroups,
}: {
  jobId: string
  open: boolean
  onClose: () => void
  onReviewGroups?: (imageGroupIds: number[], startGroupId?: number) => void
}) {
  const manager = getImportManager()
  const { queue, connection } = useImportManagerSnapshot()
  const { job, upload, detail } = useImportJob(jobId, { watch: open, scope: 'active' })
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const [busy, setBusy] = useState(false)
  const resumeFiles = useRef<HTMLInputElement>(null)
  const resumeFolder = useRef<HTMLInputElement>(null)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
    } catch {
      toast.error("That didn't work", { description: 'The server could not be reached.' })
    } finally {
      setBusy(false)
    }
  }

  const resumeWith = async (files: PickedFile[]) => {
    if (!files.length) return
    const result = await manager.resumeUpload(jobId, files)
    if (result.matched === 0) {
      toast.warning('None of those files are missing from this import', {
        description: 'Choose the same folder or files you started the import with.',
      })
    } else if (result.missing > 0) {
      toast.message(`Sending ${plural(result.matched, 'file')}`, {
        description: `${plural(result.missing, 'file')} still weren't found in what you chose.`,
      })
    }
  }

  const onResumePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = filesFromInput(e.target.files)
    // Clear the input so picking the same folder again (e.g. after a failure) fires onChange.
    e.target.value = ''
    void run(() => resumeWith(files))
  }

  const label = job?.label ?? upload?.label ?? 'Import'
  const finished = job ? isFinished(job) : upload?.phase === 'failed'

  // The editor on every group with images so far; more can be added from there later
  const reviewSoFar = async () => {
    const ids = (await manager.getDetail(jobId)).reviewable_group_ids
    if (ids.length > 0) onReviewGroups?.(ids)
  }
  const counts = job?.counts

  // Closing leaves the import running; say where to find it, once it's out of sight
  const close = () => {
    onClose()
    if (job && !finished) {
      toast(`${label} is still importing`, {
        description: 'Follow it, pause it or cancel it from Activity.',
      })
    }
  }
  const statusLine = job ? jobStatusText(job, upload) : (uploadPhaseText(upload) ?? 'Starting')

  return (
    <ImportFrame
      open={open}
      onClose={close}
      title={label}
      status={statusLine}
      footer={
        <>
          {job && !finished && (
            <div className="flex gap-2">
              {job.status === 'paused' ? (
                <TextButton
                  tone="outline"
                  onClick={() => void run(() => manager.resume(jobId))}
                  disabled={busy}
                >
                  <Play className="h-3.5 w-3.5" aria-hidden />
                  Resume
                </TextButton>
              ) : (
                <TextButton
                  tone="outline"
                  onClick={() => void run(() => manager.pause(jobId))}
                  disabled={busy}
                >
                  <Pause className="h-3.5 w-3.5" aria-hidden />
                  Pause
                </TextButton>
              )}
              <TextButton
                tone="outline-danger"
                onClick={() => setConfirmingCancel(true)}
                disabled={busy}
              >
                <Ban className="h-3.5 w-3.5" aria-hidden />
                Cancel import
              </TextButton>
            </div>
          )}
          <div className="ml-auto flex gap-2">
            <TextButton tone="outline" onClick={close}>
              Close
            </TextButton>
            {onReviewGroups && job && job.groups_reviewable > 0 && (
              <TextButton tone="solid" onClick={() => void run(reviewSoFar)} disabled={busy}>
                Review {plural(job.groups_reviewable, 'group')}
              </TextButton>
            )}
          </div>
        </>
      }
    >
      <div className="px-6 pb-4 space-y-3 shrink-0">
        {job && <ProgressSummary job={job} secondsPerItem={queue?.seconds_per_item} />}
        {upload && upload.totalBytes > 0 && !finished && upload.phase !== 'finished' && (
          <p className="font-mono text-2xs text-muted-foreground tabular-nums">
            {formatBytes(upload.sentBytes)} of {formatBytes(upload.totalBytes)} sent
          </p>
        )}

        {upload?.phase === 'failed' && upload.error && (
          <Notice tone="problem" icon={<FileWarning className="h-4 w-4" />}>
            The import couldn't start: {upload.error}
          </Notice>
        )}

        {queue?.system_paused && !finished && (
          <Notice
            tone="attention"
            icon={<PauseCircle className="h-4 w-4" />}
            actions={
              <TextButton
                onClick={() => void run(() => manager.retrySystemPause())}
                disabled={busy}
              >
                Try again now
              </TextButton>
            }
          >
            Importing is paused: {queue.reason}. It continues by itself once that's resolved.
          </Notice>
        )}

        {connection === 'lost' && (
          <Notice tone="attention" icon={<WifiOff className="h-4 w-4" />}>
            Can't reach Scene Atlas. Progress will update when the connection returns.
          </Notice>
        )}

        {job && job.waiting_for.length > 0 && !finished && (
          <Notice tone="attention" icon={<FolderOpen className="h-4 w-4" />}>
            Can't find {job.waiting_for[0]}
            {job.waiting_for.length > 1 &&
              ` and ${plural(job.waiting_for.length - 1, 'other folder')}`}
            . Reconnect the drive or put the folder back and the import carries on; other imports
            aren't affected.
          </Notice>
        )}

        {job?.upload_interrupted && (
          <Notice
            tone="attention"
            icon={<AlertTriangle className="h-4 w-4" />}
            actions={
              <>
                <TextButton onClick={() => resumeFolder.current?.click()}>Choose folder</TextButton>
                <TextButton onClick={() => resumeFiles.current?.click()}>Choose files</TextButton>
                <TextButton
                  onClick={() => void run(() => manager.finishWithoutMissing(jobId))}
                  disabled={busy}
                >
                  Finish without them
                </TextButton>
              </>
            }
          >
            The upload stopped with {plural(job.counts.awaiting_bytes, 'file')} still to send.
            Choose the same folder or files again to send the rest.
          </Notice>
        )}

        {upload && upload.failures.length > 0 && !finished && (
          <Notice
            tone="problem"
            icon={<FileWarning className="h-4 w-4" />}
            actions={
              <TextButton onClick={() => manager.retryFailedUploads(jobId)}>Try again</TextButton>
            }
          >
            {plural(upload.failures.length, 'file')} couldn't be sent.{' '}
            <span className="text-muted-foreground" title={upload.failures[0].relativePath}>
              {upload.failures[0].relativePath.split('/').pop()}: {upload.failures[0].reason}
              {upload.failures.length > 1 && ', and others'}
            </span>
          </Notice>
        )}

        {/* Always mounted, so screen readers announce the outcome when it appears */}
        <div role="status">
          {finished && counts && (
            <p className="text-xs text-foreground">
              {job?.status === 'cancelled' ? 'Cancelled. ' : 'Finished. '}
              {outcomeText(counts)}
              {counts.skipped > 0 && `, ${counts.skipped.toLocaleString()} skipped`}.
            </p>
          )}
        </div>
      </div>

      <input ref={resumeFiles} type="file" multiple className="hidden" onChange={onResumePicked} />
      <input
        ref={resumeFolder}
        type="file"
        // @ts-expect-error webkitdirectory is not in the HTMLInputElement type
        webkitdirectory=""
        multiple
        className="hidden"
        onChange={onResumePicked}
      />

      <div className="px-6 pb-4 space-y-3 border-t border-border/30 pt-3">
        <NowImporting groups={detail?.groups ?? []} planned={!!job?.planned} />
        {counts && <ProblemsLine counts={counts} />}
      </div>

      {confirmingCancel && (
        <ConfirmOverlay
          title="Cancel this import?"
          detail={
            <>
              Files that haven't been imported yet are skipped.
              {counts && counts.done > 0 && (
                <> The {plural(counts.done, 'image')} already imported stay in your library.</>
              )}
            </>
          }
          confirmLabel="Cancel import"
          tone="warning"
          busy={busy}
          onCancel={() => setConfirmingCancel(false)}
          onConfirm={() =>
            void run(async () => {
              await manager.cancel(jobId)
              setConfirmingCancel(false)
            })
          }
        />
      )}
    </ImportFrame>
  )
}
