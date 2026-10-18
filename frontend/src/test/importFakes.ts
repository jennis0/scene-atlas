/**
 * Fakes for testing import UI against a real ImportManager without a server.
 */

import { vi } from 'vitest'
import { ImportManager, setImportManager } from '@/lib/import/ImportManager'
import type { ImportClient } from '@/lib/import/importClient'
import type {
  ImportCounts,
  ImportGroupSummary,
  ImportItem,
  ImportJobDetail,
  ImportJobSummary,
  QueueStatus,
} from '@/lib/import/types'

export const idleQueue: QueueStatus = {
  running: true,
  system_paused: false,
  reason: null,
  current_job_id: null,
}

export function counts(partial: Partial<ImportCounts> = {}): ImportCounts {
  const c = {
    awaiting_bytes: 0,
    ready: 0,
    processing: 0,
    done: 0,
    duplicate: 0,
    failed: 0,
    skipped: 0,
    sorted_out: 0,
    ...partial,
  }
  return {
    ...c,
    total: c.awaiting_bytes + c.ready + c.processing + c.done + c.duplicate + c.failed + c.skipped,
  }
}

export function jobSummary(partial: Partial<ImportJobSummary> = {}): ImportJobSummary {
  return {
    id: 'job1',
    label: 'Forest Pack',
    status: 'active',
    default_image_type: 'battlemap',
    planned: true,
    dismissed: false,
    upload_interrupted: false,
    groups_done: 0,
    groups_with_images: 0,
    local: false,
    waiting_for: [],
    counts: counts(),
    group_count: 1,
    created_at: null,
    updated_at: null,
    completed_at: null,
    last_upload_at: null,
    ...partial,
  }
}

export function group(partial: Partial<ImportGroupSummary> = {}): ImportGroupSummary {
  return {
    id: 1,
    author: 'Czepeku',
    group_name: 'Island Fort',
    image_group_id: 41,
    merged_into_existing: false,
    sort_order: 0,
    counts: counts({ done: 3 }),
    ...partial,
  }
}

export function item(partial: Partial<ImportItem> = {}): ImportItem {
  return {
    id: 1,
    job_id: 'job-1',
    import_group_id: 1,
    kind: 'image',
    relative_path: 'Czepeku/Island Fort/a.png',
    filename: 'a.png',
    image_type: 'battlemap',
    size: 10,
    state: 'failed',
    attempts: 1,
    error_kind: 'file',
    error_stage: 'decode',
    error_reason: 'Image is corrupt or not a supported format',
    image_id: null,
    duplicate_of_image_id: null,
    duplicate_tier: null,
    allow_duplicate: false,
    similar_to_image_id: null,
    updated_at: null,
    classification: null,
    has_preview: false,
    ...partial,
  }
}

export interface FakeImportState {
  jobs: ImportJobSummary[]
  queue: QueueStatus
  details: Record<string, ImportJobDetail>
  items: ImportItem[]
}

/** A fake client whose responses come from a mutable state object. */
export function fakeImportClient(state: FakeImportState) {
  let version = 1
  return {
    list: vi.fn(async () => ({
      data: { jobs: state.jobs, queue: state.queue, version: version++ },
      etag: null,
    })),
    get: vi.fn(async (jobId: string) => {
      const detail = state.details[jobId]
      if (!detail) throw Object.assign(new Error('nf'), { response: { status: 404, data: {} } })
      return detail
    }),
    items: vi.fn(async (_jobId: string, params: { state?: string[] }) => ({
      items: state.items.filter((i) => !params.state || params.state.includes(i.state)),
      next_after: null,
    })),
    create: vi.fn(async (label: string | null) =>
      jobSummary({ id: 'new-job', label, planned: false }),
    ),
    manifest: vi.fn(async () => ({ items: [], ignored: 0 })),
    uploadArchive: vi.fn(),
    seal: vi.fn(async () => ({})),
    localSources: vi.fn(async () => ({ created: 1, skipped: 0, failed: 0, ignored: 0 })),
    hashes: vi.fn(async () => []),
    uploadContent: vi.fn(),
    action: vi.fn(async () => ({ affected: 1, status: 'cancelled' })),
    itemAction: vi.fn(async (_j: string, _n: string, ids?: number[]) => ({
      affected: ids?.length ?? 0,
      status: 'active',
    })),
    skipGroup: vi.fn(async () => ({ affected: 1, status: 'active' })),
    dismissFinished: vi.fn(async () => 0),
    undo: vi.fn(async () => ({ affected: 3, status: 'deleted' })),
    probeQueue: vi.fn(async () => ({ ...state.queue, system_paused: false, reason: null })),
    include: vi.fn(async (ids: number[]) => ({ affected: ids.length, job_ids: ['job1'] })),
    sortedOut: vi.fn(async () => ({
      items: state.items.filter((i) => i.error_kind === 'sorted_out'),
      truncated: false,
    })),
    sortedOutCounts: vi.fn(async () => ({}) as Record<number, number>),
  }
}

export type FakeImportClient = ReturnType<typeof fakeImportClient>

/** Install a manager over ``state`` as the app-wide one; loads the first job list. */
export async function installFakeImportManager(partial: Partial<FakeImportState> = {}) {
  const state: FakeImportState = { jobs: [], queue: idleQueue, details: {}, items: [], ...partial }
  const client = fakeImportClient(state)
  const manager = new ImportManager({
    client: client as unknown as ImportClient,
    hasher: { hash: async () => null, dispose: () => {} },
    sleep: async () => {},
    isHidden: () => false,
    win: null,
  })
  setImportManager(manager)
  await manager.refresh()
  return { state, client, manager }
}

export function uninstallFakeImportManager(manager: ImportManager) {
  manager.dispose()
  setImportManager(null)
}
