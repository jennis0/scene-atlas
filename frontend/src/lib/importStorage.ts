/**
 * localStorage persistence for import jobs.
 *
 * Stores the full editing state (groups, tags, exclusions, etc.) keyed by job_id.
 * A lightweight index (`import_jobs_index`) allows the import tray to enumerate
 * active jobs without deserialising every entry.
 *
 * Entries expire after 24 hours. Preview URLs are stripped before saving (blob URLs
 * are invalid after reload) and restored from the server preview endpoint on load.
 */

import type { EditableGroupState, ParsedTagVocab } from '@/types'
import { IMPORT_STORAGE_EXPIRY_MS } from '@/lib/constants'

// ── Persisted types ─────────────────────────────────────────────────

export interface PersistedImportJob {
  version: 1
  jobId: string
  label: string
  createdAt: string
  expiresAt: string
  savedAt: string
  groups: EditableGroupState[]
  activeTab: number
  tagVocab: ParsedTagVocab[]
}

export interface ImportJobIndexEntry {
  jobId: string
  label: string
  createdAt: string
  expiresAt: string
  totalGroups: number
  pendingGroups: number
  completedGroups: number
  failedGroups: number
  hasRunningGroups: boolean
}

export interface ImportJobsIndex {
  jobs: ImportJobIndexEntry[]
}

// ── Constants ───────────────────────────────────────────────────────

const STORAGE_PREFIX = 'import_job:'
const INDEX_KEY = 'import_jobs_index'
const EXPIRY_MS = IMPORT_STORAGE_EXPIRY_MS

// ── Save / Load ─────────────────────────────────────────────────────

export function saveImportState(
  jobId: string,
  groups: EditableGroupState[],
  activeTab: number,
  tagVocab: ParsedTagVocab[],
  label?: string,
): void {
  const now = new Date()

  // Load existing entry to preserve createdAt/expiresAt if it exists
  const existing = loadImportState(jobId)

  const entry: PersistedImportJob = {
    version: 1,
    jobId,
    label: label ?? existing?.label ?? groups[0]?.group_name ?? 'Import',
    createdAt: existing?.createdAt ?? now.toISOString(),
    expiresAt: existing?.expiresAt ?? new Date(now.getTime() + EXPIRY_MS).toISOString(),
    savedAt: now.toISOString(),
    groups: stripPreviewUrls(groups),
    activeTab,
    tagVocab,
  }

  try {
    localStorage.setItem(STORAGE_PREFIX + jobId, JSON.stringify(entry))
    updateIndex(jobId, entry)
  } catch {
    // localStorage full or unavailable — silently skip
  }
}

/**
 * Save a minimal localStorage entry for a job that has just been initialized
 * (no groups yet). This ensures the tray can see the job immediately after
 * the init endpoint returns, even before upload completes.
 */
export function saveImportJobInit(jobId: string, label: string): void {
  const now = new Date()
  const entry: PersistedImportJob = {
    version: 1,
    jobId,
    label,
    createdAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + EXPIRY_MS).toISOString(),
    savedAt: now.toISOString(),
    groups: [],
    activeTab: -1,
    tagVocab: [],
  }
  try {
    localStorage.setItem(STORAGE_PREFIX + jobId, JSON.stringify(entry))
    updateIndex(jobId, entry)
  } catch {
    // localStorage full or unavailable — silently skip
  }
}

export function loadImportState(jobId: string): PersistedImportJob | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + jobId)
    if (!raw) return null
    const parsed: PersistedImportJob = JSON.parse(raw)
    if (new Date(parsed.expiresAt) < new Date()) {
      removeImportState(jobId)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function removeImportState(jobId: string): void {
  try {
    localStorage.removeItem(STORAGE_PREFIX + jobId)
    removeFromIndex(jobId)
  } catch {
    // ignore
  }
}

// ── Index management ────────────────────────────────────────────────

export function loadImportJobsIndex(): ImportJobsIndex {
  try {
    const raw = localStorage.getItem(INDEX_KEY)
    if (!raw) return { jobs: [] }
    const index: ImportJobsIndex = JSON.parse(raw)
    // Prune expired entries
    const now = new Date()
    const valid = index.jobs.filter((j) => new Date(j.expiresAt) > now)
    if (valid.length !== index.jobs.length) {
      // Clean up expired full entries too
      for (const expired of index.jobs) {
        if (new Date(expired.expiresAt) <= now) {
          localStorage.removeItem(STORAGE_PREFIX + expired.jobId)
        }
      }
      const cleaned = { jobs: valid }
      localStorage.setItem(INDEX_KEY, JSON.stringify(cleaned))
      return cleaned
    }
    return index
  } catch {
    return { jobs: [] }
  }
}

export function cleanupExpiredImports(): void {
  loadImportJobsIndex() // Side-effect: prunes expired entries
}

function updateIndex(jobId: string, entry: PersistedImportJob): void {
  const index = loadImportJobsIndex()
  const groups = entry.groups

  const indexEntry: ImportJobIndexEntry = {
    jobId,
    label: entry.label,
    createdAt: entry.createdAt,
    expiresAt: entry.expiresAt,
    totalGroups: groups.length,
    pendingGroups: groups.filter((g) => g.status === 'pending' && !g.skip).length,
    completedGroups: groups.filter((g) => g.status === 'completed').length,
    failedGroups: groups.filter((g) => g.status === 'failed').length,
    hasRunningGroups: groups.some((g) => g.status === 'running'),
  }

  const existing = index.jobs.findIndex((j) => j.jobId === jobId)
  if (existing >= 0) {
    index.jobs[existing] = indexEntry
  } else {
    index.jobs.push(indexEntry)
  }

  try {
    localStorage.setItem(INDEX_KEY, JSON.stringify(index))
  } catch {
    // ignore
  }
}

function removeFromIndex(jobId: string): void {
  try {
    const raw = localStorage.getItem(INDEX_KEY)
    if (!raw) return
    const index: ImportJobsIndex = JSON.parse(raw)
    index.jobs = index.jobs.filter((j) => j.jobId !== jobId)
    localStorage.setItem(INDEX_KEY, JSON.stringify(index))
  } catch {
    // ignore
  }
}

// ── Helpers ─────────────────────────────────────────────────────────

/** Strip blob URLs before persisting — they're invalid after reload. */
function stripPreviewUrls(groups: EditableGroupState[]): EditableGroupState[] {
  return groups.map((g) => ({
    ...g,
    files: g.files.map((f) => ({
      ...f,
      previewUrl: undefined,
      fullImageUrl: undefined,
    })),
  }))
}

/** Build the server preview URL for a file within an import job. */
export function importPreviewUrl(jobId: string, relativePath: string): string {
  return `/api/v1/imports/${jobId}/preview/${encodeURI(relativePath)}`
}

/** Restore preview URLs from server endpoint after loading from localStorage. */
export function restorePreviewUrls(
  jobId: string,
  groups: EditableGroupState[],
): EditableGroupState[] {
  return groups.map((g) => ({
    ...g,
    files: g.files.map((f) => ({
      ...f,
      previewUrl: importPreviewUrl(jobId, f.relative_path),
    })),
  }))
}
