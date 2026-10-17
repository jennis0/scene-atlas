import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  classifyError,
  defaultLabel,
  localLabel,
  ImportManager,
  normaliseRelativePath,
  type ImportManagerOptions,
} from './ImportManager'
import type { ImportClient } from './importClient'
import type { Hasher } from './hasher'
import type { ImportJobSummary, ItemState, ManifestFile, PickedFile, QueueStatus } from './types'

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

const queue: QueueStatus = {
  running: true,
  system_paused: false,
  reason: null,
  current_job_id: null,
}

function summary(id: string, status: ImportJobSummary['status'] = 'active'): ImportJobSummary {
  const counts = {
    awaiting_bytes: 0,
    ready: 0,
    processing: 0,
    done: 0,
    duplicate: 0,
    failed: 0,
    skipped: 0,
    total: 0,
  }
  return {
    id,
    label: 'Test',
    status,
    default_image_type: 'battlemap',
    planned: true,
    dismissed: false,
    upload_interrupted: false,
    groups_done: 0,
    groups_with_images: 0,
    local: false,
    waiting_for: [],
    counts,
    group_count: 1,
    created_at: null,
    updated_at: null,
    completed_at: null,
    last_upload_at: null,
  }
}

const networkError = () => Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })
const httpError = (status: number, detail = 'nope') =>
  Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } })

type Calls = string[]

function fakeClient(calls: Calls, overrides: Partial<Record<keyof ImportClient, unknown>> = {}) {
  let nextItem = 1
  const client = {
    create: vi.fn(async () => {
      calls.push('create')
      return summary('job1')
    }),
    manifest: vi.fn(async (_jobId: string, files: ManifestFile[]) => {
      calls.push(`manifest:${files.length}`)
      return {
        items: files.map((f) => ({
          client_ref: f.client_ref ?? null,
          item_id: nextItem++,
          relative_path: f.relative_path,
          state: (f.relative_path.endsWith('.txt') ? 'skipped' : 'awaiting_bytes') as ItemState,
          error_reason: null,
        })),
        ignored: 0,
      }
    }),
    uploadArchive: vi.fn(async (_jobId: string, file: File) => {
      calls.push(`archive:${file.name}`)
      return { name: file.name, created: 1, skipped: 0, failed: 0 }
    }),
    seal: vi.fn(async () => {
      calls.push('seal')
      return {}
    }),
    localSources: vi.fn(async (_jobId: string, paths: string[]) => {
      calls.push(`local:${paths.length}`)
      return { created: 3, skipped: 0, failed: 0, ignored: 0 }
    }),
    hashes: vi.fn(async (_jobId: string, items: { item_id: number; sha256: string }[]) => {
      calls.push(`hashes:${items.length}`)
      return items.map((i) => ({
        item_id: i.item_id,
        state: 'awaiting_bytes',
        duplicate_of_image_id: null,
      }))
    }),
    uploadContent: vi.fn(
      async (
        _jobId: string,
        itemId: number,
        file: File,
        opts?: { onProgress?: (n: number) => void },
      ) => {
        calls.push(`upload:${itemId}`)
        opts?.onProgress?.(file.size)
        return { item_id: itemId, state: 'ready', error_reason: null, duplicate_of_image_id: null }
      },
    ),
    list: vi.fn(async () => ({
      data: { jobs: [summary('job1')], queue, version: 1 },
      etag: 'W/"1"',
    })),
    get: vi.fn(),
    items: vi.fn(async () => ({ items: [], next_after: null })),
    action: vi.fn(async (_jobId: string, name: string) => {
      calls.push(`action:${name}`)
      return { affected: 0, status: 'cancelled' }
    }),
    itemAction: vi.fn(async () => ({ affected: 2, status: 'active' })),
    skipGroup: vi.fn(async () => ({ affected: 1, status: 'active' })),
    undo: vi.fn(async () => ({ affected: 3, status: 'deleted' })),
    probeQueue: vi.fn(async () => queue),
    ...overrides,
  }
  return client
}

function picked(path: string, bytes = 10): PickedFile {
  return { file: new File([new Uint8Array(bytes)], path.split('/').pop()!), relativePath: path }
}

/** Calls to uploadContent, typed even when the fake was overridden. */
const uploadCalls = (client: ReturnType<typeof fakeClient>) =>
  (client.uploadContent as unknown as { mock: { calls: unknown[][] } }).mock.calls

const noHasher: Hasher = { hash: async () => null, dispose: () => {} }

function makeManager(
  client: ReturnType<typeof fakeClient>,
  opts: Partial<ImportManagerOptions> = {},
) {
  const win = { addEventListener: vi.fn(), removeEventListener: vi.fn() }
  const sleeps: number[] = []
  const manager = new ImportManager({
    client: client as unknown as ImportClient,
    hasher: noHasher,
    sleep: async (ms) => {
      sleeps.push(ms)
    },
    isHidden: () => false,
    win,
    ...opts,
  })
  return { manager, win, sleeps }
}

let managers: ImportManager[] = []
const track = <T extends { manager: ImportManager }>(m: T) => {
  managers.push(m.manager)
  return m
}

afterEach(() => {
  managers.forEach((m) => m.dispose())
  managers = []
  vi.useRealTimers()
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

describe('normaliseRelativePath', () => {
  it('matches the server rules', () => {
    expect(normaliseRelativePath('.\\Pack\\Map//a.png')).toBe('Pack/Map/a.png')
    expect(normaliseRelativePath('/a/./b.png')).toBe('a/b.png')
  })
})

describe('defaultLabel', () => {
  it('uses the single root folder', () => {
    expect(defaultLabel([picked('Forest/a.png'), picked('Forest/b/c.png')])).toBe('Forest')
  })
  it('counts files with mixed roots', () => {
    expect(defaultLabel([picked('a.png'), picked('b.png')])).toBe('2 files')
  })
})

describe('classifyError', () => {
  it('distinguishes aborted, network and http errors', () => {
    expect(classifyError({ name: 'CanceledError' })).toEqual({ kind: 'aborted' })
    expect(classifyError(networkError())).toEqual({ kind: 'network' })
    expect(classifyError(httpError(507, 'disk full'))).toEqual({
      kind: 'http',
      status: 507,
      detail: 'disk full',
    })
  })
})

// ---------------------------------------------------------------------------
// Starting imports
// ---------------------------------------------------------------------------

describe('localLabel', () => {
  it('names one folder or file by its last segment, on any platform', () => {
    expect(localLabel(['D:\\Maps\\Forest Pack'])).toBe('Forest Pack')
    expect(localLabel(['/home/me/Maps/Cave.zip'])).toBe('Cave.zip')
    expect(localLabel(['/a', '/b'])).toBe('2 folders and files')
  })
})

describe('watchJob', () => {
  it('fetches only the groups importing now until a watcher needs them all', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      get: vi.fn(async (jobId: string, scope: string) => ({
        ...summary(jobId),
        groups: [],
        scope,
      })),
    })
    const { manager } = track(makeManager(client))
    const releaseActive = manager.watchJob('job1', 'active')
    await vi.waitFor(() => expect(client.get).toHaveBeenLastCalledWith('job1', 'active'))
    const releaseAll = manager.watchJob('job1', 'all')
    await vi.waitFor(() => expect(client.get).toHaveBeenLastCalledWith('job1', 'all'))
    expect(client.get).toHaveBeenCalledTimes(2)
    releaseAll()
    releaseActive()
    expect(manager.getSnapshot().details.job1).toBeUndefined()
  })
})

describe('startLocalImport', () => {
  it('names the paths, seals, and uploads and hashes nothing', async () => {
    const calls: Calls = []
    const client = fakeClient(calls)
    const { manager, win } = track(makeManager(client))
    const jobId = await manager.startLocalImport(['/maps/Forest Pack'], { imageType: 'scene' })
    await manager.whenSettled(jobId)

    expect(calls).toEqual(['create', 'local:1', 'seal'])
    expect(client.create).toHaveBeenCalledWith('Forest Pack', 'scene')
    expect(client.uploadContent).not.toHaveBeenCalled()
    expect(client.hashes).not.toHaveBeenCalled()
    expect(manager.getSnapshot().uploads[jobId]).toMatchObject({ phase: 'finished', totalFiles: 3 })
    expect(win.removeEventListener).toHaveBeenCalled() // the unload guard is dropped again
  })

  it('reports a failure to start and cancels the job', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      localSources: vi.fn(async () => {
        throw httpError(413, 'An import can contain at most 250,000 files')
      }),
    })
    const { manager } = track(makeManager(client))
    const jobId = await manager.startLocalImport(['/maps'])
    await manager.whenSettled(jobId)
    expect(manager.getSnapshot().uploads[jobId]).toMatchObject({
      phase: 'failed',
      error: 'An import can contain at most 250,000 files',
    })
    expect(calls).toEqual(['create', 'action:cancel'])
  })
})

describe('startImport', () => {
  it('describes, seals, then uploads only files the server wants', async () => {
    const calls: Calls = []
    const client = fakeClient(calls)
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([
      picked('Pack/Map/a.png'),
      picked('Pack/Map/b.png'),
      picked('Pack/readme.txt'),
    ])
    await manager.whenSettled(jobId)

    expect(calls.filter((c) => !c.startsWith('upload'))).toEqual(['create', 'manifest:3', 'seal'])
    expect(client.uploadContent).toHaveBeenCalledTimes(2) // the .txt was skipped server-side
    const upload = manager.getSnapshot().uploads[jobId]
    expect(upload).toMatchObject({ phase: 'finished', totalFiles: 2, sentFiles: 2, label: 'Pack' })
    expect(upload.sentBytes).toBe(20)
  })

  it('sends the manifest in chunks', async () => {
    const calls: Calls = []
    const { manager } = track(makeManager(fakeClient(calls), { manifestChunk: 2 }))
    const jobId = await manager.startImport(
      ['a', 'b', 'c', 'd', 'e'].map((n) => picked(`P/${n}.png`)),
    )
    await manager.whenSettled(jobId)
    expect(calls.filter((c) => c.startsWith('manifest'))).toEqual([
      'manifest:2',
      'manifest:2',
      'manifest:1',
    ])
  })

  it('uploads zips to the archive endpoint before sealing', async () => {
    const calls: Calls = []
    const { manager } = track(makeManager(fakeClient(calls)))
    const jobId = await manager.startImport([picked('Pack.zip'), picked('Loose/a.png')])
    await manager.whenSettled(jobId)
    expect(calls.indexOf('archive:Pack.zip')).toBeLessThan(calls.indexOf('seal'))
    expect(calls).toContain('manifest:1') // the zip isn't in the manifest
  })

  it('skips uploading files the server already has (client hash)', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      hashes: vi.fn(async (_job: string, items: { item_id: number }[]) =>
        items.map((i, n) => ({
          item_id: i.item_id,
          state: n === 0 ? 'duplicate' : 'awaiting_bytes',
          duplicate_of_image_id: n === 0 ? 7 : null,
        })),
      ),
    })
    const hasher: Hasher = { hash: async () => 'a'.repeat(64), dispose: () => {} }
    const { manager } = track(makeManager(client, { hasher }))
    const jobId = await manager.startImport([picked('P/a.png'), picked('P/b.png')])
    await manager.whenSettled(jobId)
    expect(client.uploadContent).toHaveBeenCalledTimes(1)
    expect(manager.getSnapshot().uploads[jobId]).toMatchObject({
      sentFiles: 2,
      skippedAsDuplicate: 1,
    })
  })

  it('does not call the hash endpoint when hashing is unavailable', async () => {
    const calls: Calls = []
    const client = fakeClient(calls)
    const { manager } = track(makeManager(client))
    await manager.whenSettled(await manager.startImport([picked('P/a.png')]))
    expect(client.hashes).not.toHaveBeenCalled()
  })

  it('reports a failure to start and cancels the job', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      seal: vi.fn(async () => {
        throw httpError(507, 'Not enough free disk space')
      }),
    })
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png')])
    await manager.whenSettled(jobId)
    expect(manager.getSnapshot().uploads[jobId]).toMatchObject({
      phase: 'failed',
      error: 'Not enough free disk space',
    })
    expect(calls).toContain('action:cancel')
    expect(client.uploadContent).not.toHaveBeenCalled()
  })

  it('never runs more uploads at once than the concurrency limit', async () => {
    const calls: Calls = []
    let inflight = 0
    let peak = 0
    const client = fakeClient(calls, {
      uploadContent: vi.fn(async (_j: string, itemId: number) => {
        inflight++
        peak = Math.max(peak, inflight)
        await new Promise((r) => setTimeout(r, 1))
        inflight--
        return { item_id: itemId, state: 'ready', error_reason: null, duplicate_of_image_id: null }
      }),
    })
    const { manager } = track(makeManager(client, { concurrency: 2 }))
    const jobId = await manager.startImport(
      Array.from({ length: 7 }, (_, n) => picked(`P/${n}.png`)),
    )
    await manager.whenSettled(jobId)
    expect(client.uploadContent).toHaveBeenCalledTimes(7)
    expect(peak).toBe(2)
  })
})

// ---------------------------------------------------------------------------
// Upload failures
// ---------------------------------------------------------------------------

describe('upload failures', () => {
  it('waits out network loss instead of failing', async () => {
    const calls: Calls = []
    let attempts = 0
    const phases: string[] = []
    const client = fakeClient(calls, {
      uploadContent: vi.fn(async (_j: string, itemId: number) => {
        if (++attempts <= 3) throw networkError()
        return { item_id: itemId, state: 'ready', error_reason: null, duplicate_of_image_id: null }
      }),
    })
    const { manager, sleeps } = track(makeManager(client))
    manager.subscribe(() => {
      const upload = Object.values(manager.getSnapshot().uploads)[0]
      if (upload) phases.push(upload.phase)
    })
    const jobId = await manager.startImport([picked('P/a.png')])
    await manager.whenSettled(jobId)
    expect(manager.getSnapshot().uploads[jobId]).toMatchObject({
      phase: 'finished',
      sentFiles: 1,
      failures: [],
    })
    expect(phases).toContain('waiting-for-connection')
    expect(sleeps).toEqual([1000, 2000, 4000])
  })

  it('gives up on a file after repeated server errors and carries on', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      uploadContent: vi.fn(async (_j: string, itemId: number) => {
        if (itemId === 1) throw httpError(503, 'Service unavailable')
        return { item_id: itemId, state: 'ready', error_reason: null, duplicate_of_image_id: null }
      }),
    })
    const { manager } = track(makeManager(client, { maxRetries: 3 }))
    const jobId = await manager.startImport([picked('P/a.png'), picked('P/b.png')])
    await manager.whenSettled(jobId)
    const upload = manager.getSnapshot().uploads[jobId]
    expect(upload.phase).toBe('finished')
    expect(upload.sentFiles).toBe(1)
    expect(upload.failures).toEqual([{ relativePath: 'P/a.png', reason: 'Service unavailable' }])
    expect(uploadCalls(client).filter((c) => c[1] === 1)).toHaveLength(3)
  })

  it('does not retry a file the server rejects as too large', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      uploadContent: vi.fn(async () => {
        throw httpError(413, 'File exceeds the 200 MB size limit')
      }),
    })
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png')])
    await manager.whenSettled(jobId)
    expect(client.uploadContent).toHaveBeenCalledTimes(1)
    expect(manager.getSnapshot().uploads[jobId].failures[0].reason).toBe(
      'File exceeds the 200 MB size limit',
    )
  })

  it('stops quietly when the job no longer accepts bytes (409)', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      uploadContent: vi.fn(async () => {
        throw httpError(409, 'This import was cancelled')
      }),
    })
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png')])
    await manager.whenSettled(jobId)
    expect(manager.getSnapshot().uploads[jobId]).toMatchObject({ phase: 'finished', failures: [] })
  })

  it('retries setup calls through server errors', async () => {
    const calls: Calls = []
    let attempts = 0
    const client = fakeClient(calls, {
      seal: vi.fn(async () => {
        if (++attempts < 3) throw httpError(502)
        return {}
      }),
    })
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png')])
    await manager.whenSettled(jobId)
    expect(client.seal).toHaveBeenCalledTimes(3)
    expect(manager.getSnapshot().uploads[jobId].phase).toBe('finished')
  })
})

// ---------------------------------------------------------------------------
// Cancel and resume
// ---------------------------------------------------------------------------

describe('cancel', () => {
  it('aborts in-flight uploads and cancels server-side', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      uploadContent: vi.fn(
        (_j: string, _id: number, _f: File, opts?: { signal?: AbortSignal }) =>
          new Promise((_, reject) => {
            opts?.signal?.addEventListener('abort', () =>
              reject(Object.assign(new Error('canceled'), { name: 'CanceledError' })),
            )
          }),
      ),
    })
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png'), picked('P/b.png')])
    await vi.waitFor(() => expect(client.uploadContent).toHaveBeenCalled())
    await manager.cancel(jobId)
    await manager.whenSettled(jobId)
    expect(manager.getSnapshot().uploads[jobId].phase).toBe('cancelled')
    expect(calls).toContain('action:cancel')
  })
})

describe('resumeUpload', () => {
  it('sends only the files the server is still waiting for', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      items: vi.fn(async (_j: string, params: { after?: number }) =>
        params.after === undefined
          ? {
              items: [{ id: 11, relative_path: 'Pack/a.png', size: 10 }],
              next_after: 11,
            }
          : {
              items: [
                { id: 12, relative_path: 'Pack/b.png', size: 999 }, // size mismatch: different file
                { id: 13, relative_path: 'Pack/c.png', size: null },
              ],
              next_after: null,
            },
      ),
    })
    const { manager } = track(makeManager(client))
    const result = await manager.resumeUpload('job1', [
      picked('Pack\\a.png'),
      picked('Pack/b.png'),
      picked('Pack/c.png'),
      picked('Pack/extra.png'),
    ])
    expect(result).toEqual({ matched: 2, missing: 1 })
    await manager.whenSettled('job1')
    expect(
      uploadCalls(client)
        .map((c) => c[1])
        .sort(),
    ).toEqual([11, 13])
    expect(manager.getSnapshot().uploads.job1.phase).toBe('finished')
  })

  it('does nothing while an upload for the job is already running', async () => {
    const calls: Calls = []
    let release!: () => void
    const blocked = new Promise<void>((r) => (release = r))
    const items = vi.fn(async () => ({
      items: [{ id: 11, relative_path: 'Pack/a.png', size: 10 }],
      next_after: null,
    }))
    const client = fakeClient(calls, {
      items,
      uploadContent: vi.fn(async (_j: string, itemId: number) => {
        await blocked
        return { item_id: itemId, state: 'ready', error_reason: null, duplicate_of_image_id: null }
      }),
    })
    const { manager } = track(makeManager(client))
    expect(await manager.resumeUpload('job1', [picked('Pack/a.png')])).toEqual({
      matched: 1,
      missing: 0,
    })
    expect(await manager.resumeUpload('job1', [picked('Pack/a.png')])).toEqual({
      matched: 0,
      missing: 0,
    })
    expect(items).toHaveBeenCalledTimes(1)
    release()
    await manager.whenSettled('job1')
    expect(uploadCalls(client)).toHaveLength(1)
  })
})

// ---------------------------------------------------------------------------
// Unload guard
// ---------------------------------------------------------------------------

describe('beforeunload guard', () => {
  it('is attached while bytes are outstanding and removed after', async () => {
    const calls: Calls = []
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const client = fakeClient(calls, {
      uploadContent: vi.fn(async (_j: string, itemId: number) => {
        await gate
        return { item_id: itemId, state: 'ready', error_reason: null, duplicate_of_image_id: null }
      }),
    })
    const { manager, win } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png')])
    expect(win.addEventListener).toHaveBeenCalledWith('beforeunload', expect.any(Function))
    expect(manager.hasOutstandingUploads()).toBe(true)

    const handler = win.addEventListener.mock.calls[0][1] as (e: Partial<BeforeUnloadEvent>) => void
    const event = { preventDefault: vi.fn(), returnValue: undefined as unknown }
    handler(event)
    expect(event.preventDefault).toHaveBeenCalled()

    release()
    await manager.whenSettled(jobId)
    expect(win.removeEventListener).toHaveBeenCalledWith('beforeunload', handler)
    expect(manager.hasOutstandingUploads()).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

describe('polling', () => {
  beforeEach(() => vi.useFakeTimers())

  it('keeps the last data on 304 and sends the etag back', async () => {
    const calls: Calls = []
    const client = fakeClient(calls, {
      list: vi
        .fn()
        .mockResolvedValueOnce({
          data: { jobs: [summary('job1')], queue, version: 1 },
          etag: 'W/"1"',
        })
        .mockResolvedValue({ data: null, etag: 'W/"1"' }),
    })
    const { manager } = track(makeManager(client))
    await manager.refresh()
    await manager.refresh()
    expect(client.list).toHaveBeenLastCalledWith('W/"1"')
    expect(manager.getSnapshot()).toMatchObject({ loaded: true, connection: 'ok' })
    expect(manager.getSnapshot().jobs).toHaveLength(1)
  })

  it('reports degraded then lost connection, and recovers', async () => {
    const calls: Calls = []
    const list = vi.fn().mockRejectedValue(networkError())
    const { manager } = track(makeManager(fakeClient(calls, { list })))
    await manager.refresh()
    expect(manager.getSnapshot().connection).toBe('degraded')
    await manager.refresh()
    await manager.refresh()
    expect(manager.getSnapshot().connection).toBe('lost')
    list.mockResolvedValue({ data: { jobs: [], queue, version: 2 }, etag: 'W/"2"' })
    await manager.refresh()
    expect(manager.getSnapshot().connection).toBe('ok')
  })

  it('polls fast while a job is active and slowly when idle', async () => {
    const calls: Calls = []
    const list = vi
      .fn()
      .mockResolvedValue({ data: { jobs: [summary('job1')], queue, version: 1 }, etag: null })
    const { manager } = track(
      makeManager(fakeClient(calls, { list }), { pollActiveMs: 1000, pollIdleMs: 30_000 }),
    )
    manager.startPolling()
    await vi.advanceTimersByTimeAsync(0)
    expect(list).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(list).toHaveBeenCalledTimes(2)

    list.mockResolvedValue({
      data: { jobs: [summary('job1', 'completed')], queue, version: 2 },
      etag: null,
    })
    await vi.advanceTimersByTimeAsync(1000)
    expect(list).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(5000)
    expect(list).toHaveBeenCalledTimes(3) // idle: next poll in 30 s
    await vi.advanceTimersByTimeAsync(30_000)
    expect(list).toHaveBeenCalledTimes(4)
  })

  it('backs off while the server is down, but rechecks every few seconds', async () => {
    const calls: Calls = []
    const list = vi.fn().mockRejectedValue(networkError())
    const { manager } = track(
      makeManager(fakeClient(calls, { list }), { pollActiveMs: 1000, pollRetryCapMs: 5000 }),
    )
    manager.startPolling()
    await vi.advanceTimersByTimeAsync(60_000) // 0, 2, 6, 11, 16, ... 56 s
    expect(manager.getSnapshot().connection).toBe('lost')
    expect(list.mock.calls.length).toBeGreaterThanOrEqual(12)

    list.mockResolvedValue({ data: { jobs: [], queue, version: 1 }, etag: null })
    await vi.advanceTimersByTimeAsync(5000)
    expect(manager.getSnapshot().connection).toBe('ok')
  })

  it('switches an idle poller to the active cadence when an import starts', async () => {
    const calls: Calls = []
    const list = vi.fn().mockResolvedValue({ data: { jobs: [], queue, version: 1 }, etag: null })
    const { manager } = track(
      makeManager(fakeClient(calls, { list }), { pollActiveMs: 1000, pollIdleMs: 30_000 }),
    )
    manager.startPolling()
    await vi.advanceTimersByTimeAsync(0)
    expect(list).toHaveBeenCalledTimes(1) // idle: next poll armed for 30 s

    list.mockResolvedValue({ data: { jobs: [summary('job1')], queue, version: 2 }, etag: null })
    await manager.refresh() // e.g. after startImport creates the job
    expect(list).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1000)
    expect(list).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1000)
    expect(list).toHaveBeenCalledTimes(4)
  })

  it('notifies when a job finishes', async () => {
    const calls: Calls = []
    const list = vi
      .fn()
      .mockResolvedValueOnce({ data: { jobs: [summary('job1')], queue, version: 1 }, etag: null })
      .mockResolvedValue({
        data: { jobs: [summary('job1', 'completed')], queue, version: 2 },
        etag: null,
      })
    const { manager } = track(makeManager(fakeClient(calls, { list })))
    const finished: string[] = []
    manager.onJobFinished((job) => finished.push(`${job.id}:${job.status}`))
    await manager.refresh()
    await manager.refresh()
    await manager.refresh()
    expect(finished).toEqual(['job1:completed'])
  })

  it('coalesces concurrent refreshes into one request', async () => {
    const calls: Calls = []
    const client = fakeClient(calls)
    const { manager } = track(makeManager(client))
    await Promise.all([manager.refresh(), manager.refresh(), manager.refresh()])
    expect(client.list).toHaveBeenCalledTimes(1)
  })
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

describe('actions', () => {
  it('undo and dismiss drop local upload state', async () => {
    const calls: Calls = []
    const client = fakeClient(calls)
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png')])
    await manager.whenSettled(jobId)
    expect(await manager.undo(jobId)).toBe(3)
    expect(manager.getSnapshot().uploads[jobId]).toBeUndefined()
  })

  it('retry and import-as-copy pass item ids through', async () => {
    const calls: Calls = []
    const client = fakeClient(calls)
    const { manager } = track(makeManager(client))
    await manager.retry('job1', [4, 5])
    await manager.importAsCopy('job1')
    expect(client.itemAction).toHaveBeenNthCalledWith(1, 'job1', 'retry', [4, 5])
    expect(client.itemAction).toHaveBeenNthCalledWith(2, 'job1', 'import-as-copy', undefined)
  })
})

// ---------------------------------------------------------------------------
// Watching job detail and retrying local failures
// ---------------------------------------------------------------------------

describe('watchJob', () => {
  const detail = (version: number) => ({ ...summary('job1'), groups: [], version })

  it('fetches detail on watch and after changed polls only', async () => {
    const calls: Calls = []
    let version = 1
    const get = vi.fn(async () => detail(version))
    const list = vi
      .fn()
      .mockResolvedValueOnce({ data: null, etag: 'W/"1"' })
      .mockResolvedValueOnce({
        data: { jobs: [summary('job1')], queue, version: 2 },
        etag: 'W/"2"',
      })
    const { manager } = track(makeManager(fakeClient(calls, { get, list })))

    const release = manager.watchJob('job1')
    await vi.waitFor(() => expect(manager.getSnapshot().details.job1).toBeDefined())
    expect(get).toHaveBeenCalledTimes(1)

    await manager.refresh() // 304: nothing changed, no detail fetch
    expect(get).toHaveBeenCalledTimes(1)
    version = 2
    await manager.refresh() // changed: detail re-fetched
    expect(get).toHaveBeenCalledTimes(2)

    release()
    expect(manager.getSnapshot().details.job1).toBeUndefined()
  })

  it('is reference counted', async () => {
    const calls: Calls = []
    const get = vi.fn(async () => detail(1))
    const { manager } = track(makeManager(fakeClient(calls, { get })))
    const a = manager.watchJob('job1')
    const b = manager.watchJob('job1')
    await vi.waitFor(() => expect(manager.getSnapshot().details.job1).toBeDefined())
    expect(get).toHaveBeenCalledTimes(1)
    a()
    a() // releasing twice is harmless
    expect(manager.getSnapshot().details.job1).toBeDefined()
    b()
    expect(manager.getSnapshot().details.job1).toBeUndefined()
  })
})

describe('retryFailedUploads', () => {
  it('re-sends files this tab gave up on', async () => {
    const calls: Calls = []
    let rejectFirst = true
    const client = fakeClient(calls, {
      uploadContent: vi.fn(async (_j: string, itemId: number) => {
        if (itemId === 1 && rejectFirst) throw httpError(413, 'Too large')
        return { item_id: itemId, state: 'ready', error_reason: null, duplicate_of_image_id: null }
      }),
    })
    const { manager } = track(makeManager(client))
    const jobId = await manager.startImport([picked('P/a.png'), picked('P/b.png')])
    await manager.whenSettled(jobId)
    expect(manager.getSnapshot().uploads[jobId].failures).toHaveLength(1)

    rejectFirst = false
    expect(manager.retryFailedUploads(jobId)).toBe(1)
    await manager.whenSettled(jobId)
    expect(manager.getSnapshot().uploads[jobId]).toMatchObject({
      phase: 'finished',
      failures: [],
      sentFiles: 1,
      totalFiles: 1,
    })
    expect(manager.retryFailedUploads(jobId)).toBe(0) // nothing left to retry
  })
})
