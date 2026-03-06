import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  saveImportState,
  loadImportState,
  removeImportState,
  loadImportJobsIndex,
  restorePreviewUrls,
} from './importStorage'
import type { EditableGroupState } from '@/types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeGroup(overrides: Partial<EditableGroupState> = {}): EditableGroupState {
  return {
    id: 'group-1',
    author: 'Test Author',
    group_name: 'Test Group',
    files: [
      {
        relative_path: 'group/file.jpg',
        filename: 'file.jpg',
        name: 'File',
        tags: [],
        gridded: null,
        grid_width: null,
        grid_height: null,
        grid_type: null,
        subgroup: null,
        excluded: false,
        previewUrl: 'blob:http://localhost/abc123',
        fullImageUrl: 'blob:http://localhost/def456',
      },
    ],
    skip: false,
    status: 'pending',
    processed: 0,
    failed: 0,
    total: 1,
    ...overrides,
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('importStorage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  describe('saveImportState / loadImportState', () => {
    it('saves and loads a job', () => {
      const groups = [makeGroup()]
      saveImportState('job-1', groups, 0, [], 'My Import')
      const loaded = loadImportState('job-1')
      expect(loaded).not.toBeNull()
      expect(loaded?.jobId).toBe('job-1')
      expect(loaded?.label).toBe('My Import')
      expect(loaded?.activeTab).toBe(0)
    })

    it('strips blob preview URLs before saving', () => {
      const groups = [makeGroup()]
      saveImportState('job-1', groups, 0, [])
      const loaded = loadImportState('job-1')
      expect(loaded?.groups[0].files[0].previewUrl).toBeUndefined()
      expect(loaded?.groups[0].files[0].fullImageUrl).toBeUndefined()
    })

    it('preserves non-URL fields when stripping preview URLs', () => {
      const groups = [makeGroup()]
      saveImportState('job-1', groups, 0, [])
      const loaded = loadImportState('job-1')
      expect(loaded?.groups[0].files[0].filename).toBe('file.jpg')
      expect(loaded?.groups[0].files[0].name).toBe('File')
    })

    it('preserves createdAt across multiple saves', () => {
      const groups = [makeGroup()]
      saveImportState('job-1', groups, 0, [])
      const first = loadImportState('job-1')!
      saveImportState('job-1', groups, 1, [])
      const second = loadImportState('job-1')!
      expect(second.createdAt).toBe(first.createdAt)
    })

    it('updates savedAt on each save', async () => {
      const groups = [makeGroup()]
      saveImportState('job-1', groups, 0, [])
      const first = loadImportState('job-1')!.savedAt

      // Advance time slightly so savedAt changes
      await new Promise((r) => setTimeout(r, 5))
      saveImportState('job-1', groups, 0, [])
      const second = loadImportState('job-1')!.savedAt
      expect(second >= first).toBe(true)
    })

    it('uses group_name as label when no label provided', () => {
      const groups = [makeGroup({ group_name: 'Inferred Label' })]
      saveImportState('job-1', groups, 0, [])
      const loaded = loadImportState('job-1')
      expect(loaded?.label).toBe('Inferred Label')
    })

    it('returns null for a job that was never saved', () => {
      expect(loadImportState('nonexistent')).toBeNull()
    })
  })

  describe('expiry', () => {
    it('returns null for an expired job', () => {
      const groups = [makeGroup()]
      saveImportState('job-expired', groups, 0, [])

      // Manually set an already-expired expiresAt
      const raw = JSON.parse(localStorage.getItem('import_job:job-expired')!)
      raw.expiresAt = new Date(Date.now() - 1000).toISOString()
      localStorage.setItem('import_job:job-expired', JSON.stringify(raw))

      expect(loadImportState('job-expired')).toBeNull()
    })

    it('removes the localStorage entry when expired', () => {
      const groups = [makeGroup()]
      saveImportState('job-expired', groups, 0, [])
      const raw = JSON.parse(localStorage.getItem('import_job:job-expired')!)
      raw.expiresAt = new Date(Date.now() - 1000).toISOString()
      localStorage.setItem('import_job:job-expired', JSON.stringify(raw))

      loadImportState('job-expired')
      expect(localStorage.getItem('import_job:job-expired')).toBeNull()
    })
  })

  describe('removeImportState', () => {
    it('removes a saved job', () => {
      saveImportState('job-1', [makeGroup()], 0, [])
      removeImportState('job-1')
      expect(loadImportState('job-1')).toBeNull()
    })

    it('is safe to call for non-existent job', () => {
      expect(() => removeImportState('ghost-job')).not.toThrow()
    })
  })

  describe('loadImportJobsIndex', () => {
    it('returns empty index when nothing is saved', () => {
      expect(loadImportJobsIndex()).toEqual({ jobs: [] })
    })

    it('contains saved job in index', () => {
      saveImportState('job-1', [makeGroup()], 0, [], 'My Import')
      const index = loadImportJobsIndex()
      const entry = index.jobs.find((j) => j.jobId === 'job-1')
      expect(entry).toBeDefined()
      expect(entry?.label).toBe('My Import')
    })

    it('reflects group status counts', () => {
      const groups = [
        makeGroup({ id: 'g1', status: 'completed' }),
        makeGroup({ id: 'g2', status: 'failed' }),
        makeGroup({ id: 'g3', status: 'pending' }),
      ]
      saveImportState('job-1', groups, 0, [])
      const entry = loadImportJobsIndex().jobs.find((j) => j.jobId === 'job-1')!
      expect(entry.completedGroups).toBe(1)
      expect(entry.failedGroups).toBe(1)
      expect(entry.totalGroups).toBe(3)
    })

    it('prunes expired jobs from the index', () => {
      saveImportState('job-active', [makeGroup()], 0, [])
      saveImportState('job-expired', [makeGroup()], 0, [])

      const pastDate = new Date(Date.now() - 1000).toISOString()

      // Expire the full entry
      const raw = JSON.parse(localStorage.getItem('import_job:job-expired')!)
      raw.expiresAt = pastDate
      localStorage.setItem('import_job:job-expired', JSON.stringify(raw))

      // Update the index entry to match the expired date
      const indexRaw = JSON.parse(localStorage.getItem('import_jobs_index')!)
      const entry = indexRaw.jobs.find((j: { jobId: string }) => j.jobId === 'job-expired')
      if (entry) entry.expiresAt = pastDate
      localStorage.setItem('import_jobs_index', JSON.stringify(indexRaw))

      const index = loadImportJobsIndex()
      expect(index.jobs.every((j) => j.jobId !== 'job-expired')).toBe(true)
    })

    it('removes a job from the index when removeImportState is called', () => {
      saveImportState('job-1', [makeGroup()], 0, [])
      removeImportState('job-1')
      const index = loadImportJobsIndex()
      expect(index.jobs.find((j) => j.jobId === 'job-1')).toBeUndefined()
    })
  })

  describe('restorePreviewUrls', () => {
    it('sets previewUrl to server endpoint for each file', () => {
      const groups = [makeGroup()]
      const restored = restorePreviewUrls('job-1', groups)
      expect(restored[0].files[0].previewUrl).toBe('/api/v1/imports/job-1/preview/group/file.jpg')
    })

    it('does not mutate the original groups array', () => {
      const groups = [makeGroup()]
      restorePreviewUrls('job-1', groups)
      expect(groups[0].files[0].previewUrl).toBe('blob:http://localhost/abc123')
    })
  })
})
