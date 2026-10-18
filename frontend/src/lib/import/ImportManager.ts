/**
 * ImportManager: the single owner of import state in the browser
 * (ADR-018, design/ingestion.md §8.1).
 *
 * Lives outside the React tree. Dialogs and the activity dock are pure views
 * over its snapshot (via useSyncExternalStore), so remounting a component can
 * never orphan an upload or start a request loop.
 *
 * Responsibilities:
 * - Local uploads: describe files (manifest), upload archives, seal, then hash
 *   ahead of a small pool of per-file uploads. Per-file failures don't stop the
 *   rest; network loss waits for the connection instead of failing.
 * - Resume: re-pick files for an interrupted upload; only missing ones are sent.
 * - One poller for job summaries (ETag-aware, adaptive interval, backoff).
 * - A beforeunload guard while bytes are outstanding.
 *
 * The server owns the lifecycle; nothing here is persisted locally.
 */

import { importClient as defaultClient, type DetailScope, type ImportClient } from './importClient'
import { createHasher, type Hasher } from './hasher'
import type {
  ImageType,
  ImportItem,
  ImportItemPage,
  ImportJobDetail,
  ImportJobSummary,
  ItemState,
  ManifestFile,
  PickedFile,
  IncludeResult,
  QueueStatus,
  SortedOutList,
} from './types'

// Public types

export type UploadPhase =
  | 'reading' // desktop app: the server is listing the chosen folders
  | 'describing' // creating the job and sending the file list
  | 'archives' // uploading zips (expanded server-side before seal)
  | 'sealing' // server is grouping the files
  | 'uploading'
  | 'waiting-for-connection'
  | 'finished'
  | 'failed' // could not start (e.g. not enough disk space); see `error`
  | 'cancelled'

export interface LocalUploadFailure {
  relativePath: string
  reason: string
}

/** Progress of bytes this tab is sending for one job. */
export interface LocalUpload {
  jobId: string
  label: string
  phase: UploadPhase
  totalFiles: number
  /** Files the server has received, or skipped because it already had them. */
  sentFiles: number
  skippedAsDuplicate: number
  totalBytes: number
  sentBytes: number
  /** Files this tab gave up on; still waiting for bytes server-side, so resumable. */
  failures: LocalUploadFailure[]
  error: string | null
}

export type ConnectionState = 'ok' | 'degraded' | 'lost'

export interface ImportManagerSnapshot {
  jobs: ImportJobSummary[]
  queue: QueueStatus | null
  connection: ConnectionState
  uploads: Record<string, LocalUpload>
  /** Per-group detail for jobs a view is watching (see ``watchJob``). */
  details: Record<string, ImportJobDetail>
  /** True once the first job list has arrived. */
  loaded: boolean
}

export interface ResumeResult {
  matched: number
  missing: number
}

export interface StartImportOptions {
  label?: string
  imageType?: ImageType
}

export interface ImportManagerOptions {
  client?: ImportClient
  hasher?: Hasher
  /** Parallel per-file uploads. */
  concurrency?: number
  /** Files hashed (and checked with the server) per round. */
  hashBatch?: number
  manifestChunk?: number
  /** Attempts for server errors (5xx/408/429) before giving up on a file. */
  maxRetries?: number
  retryBaseMs?: number
  retryCapMs?: number
  pollActiveMs?: number
  pollHiddenMs?: number
  pollIdleMs?: number
  /** Longest wait between polls while the server is unreachable. */
  pollRetryCapMs?: number
  sleep?: (ms: number) => Promise<void>
  isHidden?: () => boolean
  /** Window to attach the beforeunload guard to (null to skip). */
  win?: Pick<Window, 'addEventListener' | 'removeEventListener'> | null
}

type Listener = () => void
type FinishedListener = (job: ImportJobSummary) => void

// Helpers

const realSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/** Mirror of the server's normalise_relative_path: the key for resume matching. */
export function normaliseRelativePath(path: string): string {
  return path
    .replace(/\\/g, '/')
    .split('/')
    .filter((p) => p !== '' && p !== '.')
    .join('/')
}

const isArchive = (path: string) => path.toLowerCase().endsWith('.zip')

type ErrorClass =
  | { kind: 'aborted' }
  | { kind: 'network' }
  | { kind: 'http'; status: number; detail: string }

interface MaybeAxiosError {
  name?: string
  code?: string
  message?: string
  response?: { status: number; data?: { detail?: unknown } }
}

export function classifyError(err: unknown): ErrorClass {
  const e = (err ?? {}) as MaybeAxiosError
  if (e.name === 'CanceledError' || e.name === 'AbortError' || e.code === 'ERR_CANCELED') {
    return { kind: 'aborted' }
  }
  if (e.response) {
    const detail = typeof e.response.data?.detail === 'string' ? e.response.data.detail : ''
    return {
      kind: 'http',
      status: e.response.status,
      detail: detail || `HTTP ${e.response.status}`,
    }
  }
  return { kind: 'network' }
}

const isRetryableStatus = (status: number) => status >= 500 || status === 408 || status === 429

class Aborted extends Error {}

const OPEN_STATUSES = new Set(['active', 'paused'])
const ACTIVE_PHASES = new Set<UploadPhase>([
  'reading',
  'describing',
  'archives',
  'sealing',
  'uploading',
  'waiting-for-connection',
])

interface PendingFile {
  itemId: number
  file: File
  relativePath: string
}

interface UploadRun {
  controller: AbortController
  settled: Promise<void>
  waitingForNetwork: number
  inflightBytes: Map<number, number>
  doneBytes: number
}

// Manager

export class ImportManager {
  private client: ImportClient
  private hasher: Hasher
  private opts: Required<
    Omit<ImportManagerOptions, 'client' | 'hasher' | 'win' | 'sleep' | 'isHidden'>
  >
  private sleep: (ms: number) => Promise<void>
  private isHidden: () => boolean
  private win: ImportManagerOptions['win']

  private snapshot: ImportManagerSnapshot = {
    jobs: [],
    queue: null,
    connection: 'ok',
    uploads: {},
    details: {},
    loaded: false,
  }
  private listeners = new Set<Listener>()
  private finishedListeners = new Set<FinishedListener>()
  private runs = new Map<string, UploadRun>()
  /** Files this tab gave up on, kept so "Try again" works without re-picking. */
  private failedFiles = new Map<string, PendingFile[]>()
  /** Jobs whose detail a mounted view needs, with a reference count. */
  /** Per watched job, one entry per watcher: the groups it needs. */
  private watched = new Map<string, DetailScope[]>()

  private etag: string | null = null
  private pollTimer: ReturnType<typeof setTimeout> | null = null
  private pollDueAt = 0
  private polling = false
  private pollInFlight: Promise<void> | null = null
  private pollFailures = 0
  private notifyTimer: ReturnType<typeof setTimeout> | null = null
  private unloadGuardAttached = false

  constructor(options: ImportManagerOptions = {}) {
    this.client = options.client ?? defaultClient
    this.hasher = options.hasher ?? createHasher()
    this.sleep = options.sleep ?? realSleep
    this.isHidden =
      options.isHidden ?? (() => typeof document !== 'undefined' && document.hidden === true)
    this.win =
      options.win === undefined ? (typeof window !== 'undefined' ? window : null) : options.win
    this.opts = {
      concurrency: options.concurrency ?? 3,
      hashBatch: options.hashBatch ?? 50,
      manifestChunk: options.manifestChunk ?? 2000,
      maxRetries: options.maxRetries ?? 5,
      retryBaseMs: options.retryBaseMs ?? 1000,
      retryCapMs: options.retryCapMs ?? 30_000,
      pollActiveMs: options.pollActiveMs ?? 1000,
      pollHiddenMs: options.pollHiddenMs ?? 5000,
      pollIdleMs: options.pollIdleMs ?? 30_000,
      // Short: a conditional GET is cheap, and the UI should notice within
      // seconds when a restarted server comes back.
      pollRetryCapMs: options.pollRetryCapMs ?? 5000,
    }
  }

  // store

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getSnapshot = (): ImportManagerSnapshot => this.snapshot

  /** Called with each job that moves from active/paused to completed/cancelled. */
  onJobFinished(listener: FinishedListener): () => void {
    this.finishedListeners.add(listener)
    return () => this.finishedListeners.delete(listener)
  }

  private set(patch: Partial<ImportManagerSnapshot>, coalesce = false): void {
    this.snapshot = { ...this.snapshot, ...patch }
    if (!coalesce) {
      if (this.notifyTimer) clearTimeout(this.notifyTimer)
      this.notifyTimer = null
      this.notify()
    } else if (!this.notifyTimer) {
      // Upload progress fires very often; re-render at most ~10×/s.
      this.notifyTimer = setTimeout(() => {
        this.notifyTimer = null
        this.notify()
      }, 100)
    }
  }

  private notify(): void {
    for (const listener of this.listeners) listener()
  }

  private updateUpload(jobId: string, patch: Partial<LocalUpload>, coalesce = false): void {
    const current = this.snapshot.uploads[jobId]
    if (!current) return
    this.set({ uploads: { ...this.snapshot.uploads, [jobId]: { ...current, ...patch } } }, coalesce)
    this.syncUnloadGuard()
  }

  // starting an import

  /**
   * Start importing ``files``. Resolves with the job id as soon as the job
   * exists; describing, sealing and uploading continue in the background
   * (``whenSettled`` waits for them).
   */
  async startImport(files: PickedFile[], options: StartImportOptions = {}): Promise<string> {
    return this.startRun(
      options.label ?? defaultLabel(files),
      options,
      'describing',
      (jobId, run) => this.runImport(jobId, files, run),
    )
  }

  /**
   * Desktop app: import files and folders on this computer by path
   * (design/local-ingest.md). The server lists them and reads each file where it
   * is, so nothing is hashed or uploaded here and there's nothing to resume.
   */
  async startLocalImport(paths: string[], options: StartImportOptions = {}): Promise<string> {
    return this.startRun(options.label ?? localLabel(paths), options, 'reading', (jobId, run) =>
      this.runLocalImport(jobId, paths, run),
    )
  }

  private async startRun(
    label: string,
    options: StartImportOptions,
    phase: UploadPhase,
    body: (jobId: string, run: UploadRun) => Promise<void>,
  ): Promise<string> {
    const job = await this.client.create(label, options.imageType ?? 'battlemap')
    this.set({
      uploads: {
        ...this.snapshot.uploads,
        [job.id]: {
          jobId: job.id,
          label,
          phase,
          totalFiles: 0,
          sentFiles: 0,
          skippedAsDuplicate: 0,
          totalBytes: 0,
          sentBytes: 0,
          failures: [],
          error: null,
        },
      },
    })
    this.syncUnloadGuard()
    const run = this.newRun(job.id)
    run.settled = this.settle(job.id, body(job.id, run))
    void this.refresh()
    return job.id
  }

  /** Record how a run that starts a job ended: finished, cancelled, or failed to start. */
  private async settle(jobId: string, work: Promise<void>): Promise<void> {
    try {
      await work
      this.updateUpload(jobId, { phase: 'finished' })
    } catch (err) {
      if (err instanceof Aborted || classifyError(err).kind === 'aborted') {
        this.updateUpload(jobId, { phase: 'cancelled' })
      } else {
        const error = classifyError(err)
        const message =
          error.kind === 'http' ? error.detail : 'Lost connection to the server while starting'
        this.updateUpload(jobId, { phase: 'failed', error: message })
        // A job that never got going would otherwise sit active forever.
        await this.client.action(jobId, 'cancel').catch(() => {})
      }
    } finally {
      void this.refresh()
    }
  }

  /** Resolves when this tab's work for ``jobId`` has finished (tests, callers that wait). */
  whenSettled(jobId: string): Promise<void> {
    return this.runs.get(jobId)?.settled ?? Promise.resolve()
  }

  private newRun(jobId: string): UploadRun {
    const run: UploadRun = {
      controller: new AbortController(),
      settled: Promise.resolve(),
      waitingForNetwork: 0,
      inflightBytes: new Map(),
      doneBytes: 0,
    }
    this.runs.set(jobId, run)
    return run
  }

  private async runImport(jobId: string, files: PickedFile[], run: UploadRun): Promise<void> {
    const archives = files.filter((f) => isArchive(f.relativePath))
    const others = files.filter((f) => !isArchive(f.relativePath))

    const pending = await this.describe(jobId, others, run)

    if (archives.length) {
      this.updateUpload(jobId, { phase: 'archives' })
      for (const archive of archives) {
        await this.withRetries(run, () =>
          this.client.uploadArchive(jobId, archive.file, { signal: run.controller.signal }),
        )
      }
    }

    this.updateUpload(jobId, { phase: 'sealing' })
    await this.withRetries(run, () => this.client.seal(jobId))
    void this.refresh()

    this.updateUpload(jobId, {
      phase: 'uploading',
      totalFiles: pending.length,
      totalBytes: pending.reduce((sum, p) => sum + p.file.size, 0),
    })
    await this.uploadAll(jobId, pending, run)
  }

  private async runLocalImport(jobId: string, paths: string[], run: UploadRun): Promise<void> {
    const added = await this.withRetries(run, () => this.client.localSources(jobId, paths))
    this.updateUpload(jobId, { phase: 'sealing', totalFiles: added.created })
    await this.withRetries(run, () => this.client.seal(jobId))
  }

  /** Send the file list in chunks; returns the files whose bytes the server wants. */
  private async describe(
    jobId: string,
    files: PickedFile[],
    run: UploadRun,
  ): Promise<PendingFile[]> {
    const pending: PendingFile[] = []
    for (let start = 0; start < files.length; start += this.opts.manifestChunk) {
      const chunk = files.slice(start, start + this.opts.manifestChunk)
      const entries: ManifestFile[] = chunk.map((f, i) => ({
        client_ref: String(start + i),
        relative_path: f.relativePath,
        size: f.file.size,
        last_modified: f.file.lastModified,
      }))
      const response = await this.withRetries(run, () => this.client.manifest(jobId, entries))
      for (const item of response.items) {
        const picked = files[Number(item.client_ref)]
        if (picked && item.state === 'awaiting_bytes') {
          pending.push({
            itemId: item.item_id,
            file: picked.file,
            relativePath: picked.relativePath,
          })
        }
      }
    }
    return pending
  }

  // resuming

  /**
   * Resume an interrupted upload with files the user re-picked. Files are
   * matched to what the server is still waiting for by path (and size, when
   * known); only those are sent.
   */
  async resumeUpload(jobId: string, files: PickedFile[], label?: string): Promise<ResumeResult> {
    if (this.isUploading(jobId)) return { matched: 0, missing: 0 }
    const awaiting: ImportItem[] = []
    let after: number | undefined
    do {
      const page = await this.client.items(jobId, { state: ['awaiting_bytes'], after, limit: 1000 })
      awaiting.push(...page.items)
      after = page.next_after ?? undefined
    } while (after !== undefined)

    const byPath = new Map(files.map((f) => [normaliseRelativePath(f.relativePath), f]))
    const pending: PendingFile[] = []
    for (const item of awaiting) {
      const picked = byPath.get(item.relative_path)
      if (picked && (item.size == null || item.size === picked.file.size)) {
        pending.push({ itemId: item.id, file: picked.file, relativePath: picked.relativePath })
      }
    }

    // Paging the item list is async: another run may have started meanwhile.
    if (this.isUploading(jobId)) return { matched: 0, missing: 0 }
    this.startUploadRun(jobId, pending, label)
    return { matched: pending.length, missing: awaiting.length - pending.length }
  }

  /** Try again to send the files this tab gave up on (no re-picking needed). */
  retryFailedUploads(jobId: string): number {
    const pending = this.failedFiles.get(jobId) ?? []
    if (!pending.length || this.isUploading(jobId)) return 0
    this.failedFiles.delete(jobId)
    this.startUploadRun(jobId, pending)
    return pending.length
  }

  private isUploading(jobId: string): boolean {
    const phase = this.snapshot.uploads[jobId]?.phase
    return phase !== undefined && ACTIVE_PHASES.has(phase)
  }

  /** Upload already-described files for a sealed job (resume and retry). */
  private startUploadRun(jobId: string, pending: PendingFile[], label?: string): void {
    const existing = this.snapshot.jobs.find((j) => j.id === jobId)
    this.set({
      uploads: {
        ...this.snapshot.uploads,
        [jobId]: {
          jobId,
          label: label ?? this.snapshot.uploads[jobId]?.label ?? existing?.label ?? 'Import',
          phase: 'uploading',
          totalFiles: pending.length,
          sentFiles: 0,
          skippedAsDuplicate: 0,
          totalBytes: pending.reduce((sum, p) => sum + p.file.size, 0),
          sentBytes: 0,
          failures: [],
          error: null,
        },
      },
    })
    this.syncUnloadGuard()
    const run = this.newRun(jobId)
    run.settled = (async () => {
      try {
        await this.uploadAll(jobId, pending, run)
        this.updateUpload(jobId, { phase: 'finished' })
      } catch {
        this.updateUpload(jobId, { phase: 'cancelled' })
      } finally {
        void this.refresh()
      }
    })()
  }

  // uploading

  private async uploadAll(jobId: string, files: PendingFile[], run: UploadRun): Promise<void> {
    const queue: PendingFile[] = []
    let producing = true
    let wake: (() => void) | null = null
    const signalWork = () => {
      wake?.()
      wake = null
    }

    // Producer: hash a round of files ahead, let the server skip known ones,
    // queue the rest. Uploads start as soon as the first round is queued.
    const producer = (async () => {
      try {
        for (let start = 0; start < files.length; start += this.opts.hashBatch) {
          this.throwIfAborted(run)
          const round = files.slice(start, start + this.opts.hashBatch)
          const toUpload = await this.skipKnownFiles(jobId, round, run)
          queue.push(...toUpload)
          signalWork()
        }
      } finally {
        producing = false
        signalWork()
      }
    })()

    const worker = async () => {
      for (;;) {
        this.throwIfAborted(run)
        const next = queue.shift()
        if (next) {
          await this.uploadOne(jobId, next, run)
          continue
        }
        if (!producing) return
        await new Promise<void>((resolve) => {
          const previous = wake
          wake = () => {
            previous?.()
            resolve()
          }
        })
      }
    }

    await Promise.all([producer, ...Array.from({ length: this.opts.concurrency }, worker)])
  }

  /** Hash a round and ask the server which it already has. Returns files to upload. */
  private async skipKnownFiles(
    jobId: string,
    round: PendingFile[],
    run: UploadRun,
  ): Promise<PendingFile[]> {
    const hashed: { item_id: number; sha256: string }[] = []
    for (const pending of round) {
      this.throwIfAborted(run)
      const sha256 = await this.hasher.hash(pending.file)
      if (sha256) hashed.push({ item_id: pending.itemId, sha256 })
    }
    if (!hashed.length) return round

    let results
    try {
      results = await this.withRetries(run, () => this.client.hashes(jobId, hashed))
    } catch (err) {
      if (classifyError(err).kind === 'aborted' || err instanceof Aborted) throw err
      return round // skipping known files is an optimisation; upload everything
    }
    const known = new Set(results.filter((r) => r.state !== 'awaiting_bytes').map((r) => r.item_id))
    if (known.size) {
      const skippedBytes = round
        .filter((p) => known.has(p.itemId))
        .reduce((sum, p) => sum + p.file.size, 0)
      run.doneBytes += skippedBytes
      const upload = this.snapshot.uploads[jobId]
      this.updateUpload(jobId, {
        sentFiles: upload.sentFiles + known.size,
        skippedAsDuplicate: upload.skippedAsDuplicate + known.size,
        sentBytes: this.sentBytes(run),
      })
    }
    return round.filter((p) => !known.has(p.itemId))
  }

  private async uploadOne(jobId: string, pending: PendingFile, run: UploadRun): Promise<void> {
    let serverErrors = 0
    let networkAttempts = 0
    for (;;) {
      this.throwIfAborted(run)
      try {
        await this.client.uploadContent(jobId, pending.itemId, pending.file, {
          signal: run.controller.signal,
          onProgress: (loaded) => {
            run.inflightBytes.set(pending.itemId, loaded)
            this.updateUpload(jobId, { sentBytes: this.sentBytes(run) }, true)
          },
        })
        this.finishFile(jobId, pending, run)
        return
      } catch (err) {
        run.inflightBytes.delete(pending.itemId)
        const error = classifyError(err)
        if (error.kind === 'aborted') throw err
        if (error.kind === 'network') {
          // Never fail an import because the network dropped: wait and retry.
          await this.waitForNetwork(jobId, run, ++networkAttempts)
          continue
        }
        if (isRetryableStatus(error.status) && ++serverErrors < this.opts.maxRetries) {
          await this.sleep(this.backoff(serverErrors))
          continue
        }
        if (error.status === 409 || error.status === 404) {
          // The job was cancelled or the item no longer takes bytes; nothing to do.
          this.finishFile(jobId, pending, run, false)
          return
        }
        this.recordFailure(jobId, pending, run, error.detail)
        return
      }
    }
  }

  private finishFile(jobId: string, pending: PendingFile, run: UploadRun, counted = true): void {
    run.inflightBytes.delete(pending.itemId)
    run.doneBytes += pending.file.size
    const upload = this.snapshot.uploads[jobId]
    this.updateUpload(jobId, {
      sentFiles: upload.sentFiles + (counted ? 1 : 0),
      sentBytes: this.sentBytes(run),
    })
  }

  private recordFailure(jobId: string, pending: PendingFile, run: UploadRun, reason: string): void {
    run.inflightBytes.delete(pending.itemId)
    this.failedFiles.set(jobId, [...(this.failedFiles.get(jobId) ?? []), pending])
    const upload = this.snapshot.uploads[jobId]
    this.updateUpload(jobId, {
      failures: [...upload.failures, { relativePath: pending.relativePath, reason }],
      totalBytes: upload.totalBytes - pending.file.size,
      sentBytes: this.sentBytes(run),
    })
  }

  private async waitForNetwork(jobId: string, run: UploadRun, attempt: number): Promise<void> {
    run.waitingForNetwork++
    this.updateUpload(jobId, { phase: 'waiting-for-connection' })
    try {
      await this.sleep(this.backoff(attempt))
    } finally {
      run.waitingForNetwork--
      if (
        run.waitingForNetwork === 0 &&
        this.snapshot.uploads[jobId]?.phase === 'waiting-for-connection'
      ) {
        this.updateUpload(jobId, { phase: 'uploading' })
      }
    }
  }

  /** Retry a setup request (manifest, seal, archive, hashes) through outages and 5xx. */
  private async withRetries<T>(run: UploadRun, fn: () => Promise<T>): Promise<T> {
    let serverErrors = 0
    let networkAttempts = 0
    for (;;) {
      this.throwIfAborted(run)
      try {
        return await fn()
      } catch (err) {
        const error = classifyError(err)
        if (error.kind === 'network') {
          await this.sleep(this.backoff(++networkAttempts))
          continue
        }
        if (
          error.kind === 'http' &&
          isRetryableStatus(error.status) &&
          ++serverErrors < this.opts.maxRetries
        ) {
          await this.sleep(this.backoff(serverErrors))
          continue
        }
        throw err
      }
    }
  }

  private backoff(attempt: number): number {
    return Math.min(this.opts.retryCapMs, this.opts.retryBaseMs * 2 ** (attempt - 1))
  }

  private sentBytes(run: UploadRun): number {
    let inflight = 0
    for (const loaded of run.inflightBytes.values()) inflight += loaded
    return run.doneBytes + inflight
  }

  private throwIfAborted(run: UploadRun): void {
    if (run.controller.signal.aborted) throw new Aborted()
  }

  // job actions

  /** Stop this tab's uploads for the job and cancel it server-side (finished work is kept). */
  async cancel(jobId: string): Promise<void> {
    this.runs.get(jobId)?.controller.abort()
    await this.client.action(jobId, 'cancel')
    await this.refresh()
  }

  async pause(jobId: string): Promise<void> {
    await this.client.action(jobId, 'pause')
    await this.refresh()
  }

  async resume(jobId: string): Promise<void> {
    await this.client.action(jobId, 'resume')
    await this.refresh()
  }

  async finishWithoutMissing(jobId: string): Promise<void> {
    this.runs.get(jobId)?.controller.abort()
    await this.client.action(jobId, 'finish-upload')
    await this.refresh()
  }

  async dismiss(jobId: string): Promise<void> {
    await this.client.action(jobId, 'dismiss')
    this.forgetUpload(jobId)
    await this.refresh()
  }

  /** Hide every finished import from the activity dock. */
  async dismissFinished(): Promise<void> {
    const finished = this.snapshot.jobs.filter((j) => !OPEN_STATUSES.has(j.status)).map((j) => j.id)
    await this.client.dismissFinished()
    finished.forEach((id) => this.forgetUpload(id))
    await this.refresh()
  }

  async retry(jobId: string, itemIds?: number[]): Promise<number> {
    const result = await this.client.itemAction(jobId, 'retry', itemIds)
    await this.refresh()
    return result.affected
  }

  async importAsCopy(jobId: string, itemIds?: number[]): Promise<number> {
    const result = await this.client.itemAction(jobId, 'import-as-copy', itemIds)
    await this.refresh()
    return result.affected
  }

  /** Import items Auto sorted out after all; says how many, and which imports re-opened */
  async include(itemIds: number[]): Promise<IncludeResult> {
    const result = await this.client.include(itemIds)
    await this.refresh()
    return result
  }

  listSortedOut(imageGroupId: number): Promise<SortedOutList> {
    return this.client.sortedOut(imageGroupId)
  }

  sortedOutCounts(): Promise<Record<number, number>> {
    return this.client.sortedOutCounts()
  }

  async skipGroup(jobId: string, groupId: number): Promise<void> {
    await this.client.skipGroup(jobId, groupId)
    await this.refresh()
  }

  /** Undo: delete every image the import created, then the import itself. */
  async undo(jobId: string): Promise<number> {
    this.runs.get(jobId)?.controller.abort()
    const result = await this.client.undo(jobId)
    this.forgetUpload(jobId)
    await this.refresh()
    return result.affected
  }

  async retrySystemPause(): Promise<void> {
    const queue = await this.client.probeQueue()
    this.set({ queue })
  }

  private forgetUpload(jobId: string): void {
    this.failedFiles.delete(jobId)
    if (!(jobId in this.snapshot.uploads)) return
    const uploads = { ...this.snapshot.uploads }
    delete uploads[jobId]
    this.set({ uploads })
    this.syncUnloadGuard()
  }

  /** A page of one job's items (for the report); not cached. */
  listItems(
    jobId: string,
    params: { state?: ItemState[]; after?: number; limit?: number },
  ): Promise<ImportItemPage> {
    return this.client.items(jobId, params)
  }

  // job detail

  /**
   * Keep ``snapshot.details[jobId]`` fresh while the returned function hasn't
   * been called. Detail is re-fetched only when the summary poll reports a
   * change, so an idle open dialog costs nothing. ``active`` watchers need only
   * the groups importing now; the detail carries every group if any watcher
   * asks for ``all``.
   */
  watchJob(jobId: string, scope: DetailScope = 'all'): () => void {
    const before = this.detailScope(jobId)
    this.watched.set(jobId, [...(this.watched.get(jobId) ?? []), scope])
    if (this.detailScope(jobId) !== before) void this.fetchDetail(jobId)
    let released = false
    return () => {
      if (released) return
      released = true
      const scopes = [...(this.watched.get(jobId) ?? [])]
      scopes.splice(scopes.indexOf(scope), 1)
      if (scopes.length > 0) {
        this.watched.set(jobId, scopes)
        return
      }
      this.watched.delete(jobId)
      const details = { ...this.snapshot.details }
      delete details[jobId]
      this.set({ details })
    }
  }

  /** One-off fetch of a job's per-group detail (e.g. to open its groups in the editor). */
  getDetail(jobId: string): Promise<ImportJobDetail> {
    return this.client.get(jobId)
  }

  private detailScope(jobId: string): DetailScope | undefined {
    const scopes = this.watched.get(jobId)
    if (!scopes?.length) return undefined
    return scopes.includes('all') ? 'all' : 'active'
  }

  private async fetchDetail(jobId: string): Promise<void> {
    try {
      const detail = await this.client.get(jobId, this.detailScope(jobId))
      if (this.watched.has(jobId)) {
        this.set({ details: { ...this.snapshot.details, [jobId]: detail } })
      }
    } catch {
      // Gone (undone elsewhere) or unreachable; the summary poll reports which.
    }
  }

  // polling

  /** Start the single job-summary poller (idempotent). */
  startPolling(): void {
    if (this.polling) return
    this.polling = true
    this.schedulePoll(0)
  }

  stopPolling(): void {
    this.polling = false
    if (this.pollTimer) clearTimeout(this.pollTimer)
    this.pollTimer = null
  }

  /** Poll now (after an action, or when the user asks). */
  async refresh(): Promise<void> {
    if (this.pollInFlight) return this.pollInFlight
    this.pollInFlight = this.poll().finally(() => {
      this.pollInFlight = null
      this.pullPollForward()
    })
    return this.pollInFlight
  }

  private schedulePoll(delay: number): void {
    if (!this.polling) return
    if (this.pollTimer) clearTimeout(this.pollTimer)
    this.pollDueAt = Date.now() + delay
    this.pollTimer = setTimeout(async () => {
      this.pollTimer = null
      await this.refresh()
      this.schedulePoll(this.nextPollDelay())
    }, delay)
  }

  /**
   * After an out-of-band poll (an action, a new import), bring the armed timer
   * forward if the cadence just got faster — otherwise an import started while
   * idle would wait out the 30 s idle timer before its progress moved.
   */
  private pullPollForward(): void {
    if (!this.polling || !this.pollTimer) return
    const delay = this.nextPollDelay()
    if (Date.now() + delay < this.pollDueAt) this.schedulePoll(delay)
  }

  private nextPollDelay(): number {
    if (this.pollFailures > 0) {
      return Math.min(this.opts.pollRetryCapMs, this.opts.pollActiveMs * 2 ** this.pollFailures)
    }
    if (this.isHidden()) return this.opts.pollHiddenMs
    return this.hasActivity() ? this.opts.pollActiveMs : this.opts.pollIdleMs
  }

  private hasActivity(): boolean {
    return (
      this.snapshot.jobs.some((j) => OPEN_STATUSES.has(j.status) && j.planned) ||
      Object.values(this.snapshot.uploads).some((u) => ACTIVE_PHASES.has(u.phase))
    )
  }

  private async poll(): Promise<void> {
    try {
      const { data, etag } = await this.client.list(this.etag)
      this.etag = etag
      this.pollFailures = 0
      if (!data) {
        if (this.snapshot.connection !== 'ok') this.set({ connection: 'ok' })
        return
      }
      const previous = new Map(this.snapshot.jobs.map((j) => [j.id, j.status]))
      this.set({ jobs: data.jobs, queue: data.queue, connection: 'ok', loaded: true })
      await Promise.all([...this.watched.keys()].map((jobId) => this.fetchDetail(jobId)))
      for (const job of data.jobs) {
        const before = previous.get(job.id)
        if (before && OPEN_STATUSES.has(before) && !OPEN_STATUSES.has(job.status)) {
          for (const listener of this.finishedListeners) listener(job)
        }
      }
    } catch {
      this.pollFailures++
      const connection: ConnectionState = this.pollFailures >= 3 ? 'lost' : 'degraded'
      if (this.snapshot.connection !== connection) this.set({ connection })
    }
  }

  // unload guard

  /** True while this tab still has bytes to send. */
  hasOutstandingUploads(): boolean {
    return Object.values(this.snapshot.uploads).some((u) => ACTIVE_PHASES.has(u.phase))
  }

  private onBeforeUnload = (event: BeforeUnloadEvent): void => {
    if (!this.hasOutstandingUploads()) return
    event.preventDefault()
    event.returnValue = '' // legacy browsers need a value to show the prompt
  }

  private syncUnloadGuard(): void {
    if (!this.win) return
    const needed = this.hasOutstandingUploads()
    if (needed && !this.unloadGuardAttached) {
      this.win.addEventListener('beforeunload', this.onBeforeUnload as EventListener)
      this.unloadGuardAttached = true
    } else if (!needed && this.unloadGuardAttached) {
      this.win.removeEventListener('beforeunload', this.onBeforeUnload as EventListener)
      this.unloadGuardAttached = false
    }
  }

  /** Tear down timers, workers and listeners (tests). */
  dispose(): void {
    this.stopPolling()
    for (const run of this.runs.values()) run.controller.abort()
    if (this.notifyTimer) clearTimeout(this.notifyTimer)
    if (this.win && this.unloadGuardAttached) {
      this.win.removeEventListener('beforeunload', this.onBeforeUnload as EventListener)
    }
    this.hasher.dispose()
    this.listeners.clear()
    this.finishedListeners.clear()
  }
}

/** "Forest Pack" for a single dropped folder, "Forest Pack.zip" for a zip, else "12 files". */
export function defaultLabel(files: PickedFile[]): string {
  const roots = new Set(files.map((f) => normaliseRelativePath(f.relativePath).split('/')[0]))
  if (roots.size === 1) return [...roots][0]
  return `${files.length} file${files.length === 1 ? '' : 's'}`
}

/** "Forest Pack" for one folder or file, else "3 folders and files". */
export function localLabel(paths: string[]): string {
  if (paths.length === 1) {
    const parts = paths[0].split(/[\\/]/).filter(Boolean)
    return parts[parts.length - 1] ?? paths[0]
  }
  return `${paths.length} folders and files`
}

let instance: ImportManager | null = null

/** The app-wide manager. */
export function getImportManager(): ImportManager {
  instance ??= new ImportManager()
  return instance
}

/** Replace the app-wide manager (tests). Pass null to reset. */
export function setImportManager(manager: ImportManager | null): void {
  instance = manager
}
