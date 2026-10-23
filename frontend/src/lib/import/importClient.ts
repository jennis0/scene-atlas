/**
 * HTTP client for the imports API (ADR-018, design/ingestion.md §7).
 *
 * Thin and typed; retry and backoff policy lives in ImportManager, which is the
 * only intended caller.
 */

import { api } from '@/lib/api/_client'
import type {
  ActionResult,
  ArchiveResult,
  LocalSourcesResult,
  ContentResult,
  HashResult,
  ImageType,
  ImportItemPage,
  ImportJobDetail,
  ImportJobList,
  ImportJobSummary,
  ItemState,
  ManifestFile,
  IncludeResult,
  ManifestResponse,
  PickedFile,
  QueueStatus,
  SortedOutList,
} from './types'

const BASE = '/imports'

export interface UploadOptions {
  signal?: AbortSignal
  onProgress?: (loadedBytes: number) => void
}

/** Result of a conditional list request: null when unchanged (HTTP 304). */
export interface ListResult {
  data: ImportJobList | null
  etag: string | null
}

const rawBody = { 'Content-Type': 'application/octet-stream' }

export const importClient = {
  async list(etag: string | null, includeDismissed = false): Promise<ListResult> {
    const response = await api.get<ImportJobList>(BASE, {
      params: { include_dismissed: includeDismissed || undefined },
      headers: etag ? { 'If-None-Match': etag } : undefined,
      validateStatus: (status) => status === 200 || status === 304,
    })
    const newEtag = (response.headers?.etag as string | undefined) ?? etag
    return { data: response.status === 304 ? null : response.data, etag: newEtag }
  },

  /** The job and its groups (none until its groups have been identified). */
  async get(jobId: string): Promise<ImportJobDetail> {
    const { data } = await api.get<ImportJobDetail>(`${BASE}/${jobId}`)
    return data
  },

  async items(
    jobId: string,
    params: {
      state?: ItemState[]
      after?: number
      limit?: number
    } = {},
  ): Promise<ImportItemPage> {
    const { data } = await api.get<ImportItemPage>(`${BASE}/${jobId}/items`, {
      params: {
        state: params.state,
        after: params.after,
        limit: params.limit,
      },
    })
    return data
  },

  async create(label: string | null, imageType: ImageType): Promise<ImportJobSummary> {
    const { data } = await api.post<ImportJobSummary>(BASE, {
      label,
      default_image_type: imageType,
    })
    return data
  },

  async manifest(jobId: string, files: ManifestFile[]): Promise<ManifestResponse> {
    const { data } = await api.post<ManifestResponse>(`${BASE}/${jobId}/manifest`, { files })
    return data
  },

  /** Upload a zip, named by its relative path so the server knows the folder it was in. */
  async uploadArchive(
    jobId: string,
    archive: PickedFile,
    options: UploadOptions = {},
  ): Promise<ArchiveResult> {
    const { data } = await api.put<ArchiveResult>(`${BASE}/${jobId}/archives`, archive.file, {
      params: { name: archive.relativePath },
      headers: rawBody,
      timeout: 0,
      signal: options.signal,
      onUploadProgress: (e) => options.onProgress?.(e.loaded),
    })
    return data
  },

  /** Desktop app: add files and folders by path; the server lists and reads them. */
  async localSources(jobId: string, paths: string[]): Promise<LocalSourcesResult> {
    const { data } = await api.post<LocalSourcesResult>(
      `${BASE}/${jobId}/local-sources`,
      { paths },
      { timeout: 0 }, // listing a large library takes a few seconds, longer on a slow drive
    )
    return data
  },

  async seal(jobId: string): Promise<ImportJobDetail> {
    const { data } = await api.post<ImportJobDetail>(`${BASE}/${jobId}/seal`, undefined, {
      timeout: 0, // grouping tens of thousands of paths can take a while
    })
    return data
  },

  async hashes(jobId: string, items: { item_id: number; sha256: string }[]): Promise<HashResult[]> {
    const { data } = await api.post<{ items: HashResult[] }>(`${BASE}/${jobId}/hashes`, { items })
    return data.items
  },

  async uploadContent(
    jobId: string,
    itemId: number,
    file: File,
    options: UploadOptions = {},
  ): Promise<ContentResult> {
    const { data } = await api.put<ContentResult>(
      `${BASE}/${jobId}/items/${itemId}/content`,
      file,
      {
        headers: rawBody,
        timeout: 0,
        signal: options.signal,
        onUploadProgress: (e) => options.onProgress?.(e.loaded),
      },
    )
    return data
  },

  async action(
    jobId: string,
    name: 'pause' | 'resume' | 'cancel' | 'finish-upload' | 'dismiss',
  ): Promise<ActionResult> {
    const { data } = await api.post<ActionResult>(`${BASE}/${jobId}/${name}`)
    return data
  },

  async itemAction(
    jobId: string,
    name: 'retry' | 'import-as-copy',
    itemIds?: number[],
  ): Promise<ActionResult> {
    const { data } = await api.post<ActionResult>(`${BASE}/${jobId}/${name}`, {
      item_ids: itemIds ?? null,
    })
    return data
  },

  /** Hide every finished import from the activity dock; returns how many */
  async dismissFinished(): Promise<number> {
    const { data } = await api.post<{ dismissed: number }>(`${BASE}/dismiss-finished`)
    return data.dismissed
  },

  async undo(jobId: string): Promise<ActionResult> {
    const { data } = await api.delete<ActionResult>(`${BASE}/${jobId}`)
    return data
  },

  /** Import items Auto sorted out after all, across imports */
  async include(itemIds: number[]): Promise<IncludeResult> {
    const { data } = await api.post<IncludeResult>(`${BASE}/include`, { item_ids: itemIds })
    return data
  },

  async sortedOut(imageGroupId: number): Promise<SortedOutList> {
    const { data } = await api.get<SortedOutList>(`${BASE}/sorted-out`, {
      params: { image_group_id: imageGroupId },
    })
    return data
  },

  /** Gallery group id → items Auto sorted out of it, for groups that have any */
  async sortedOutCounts(): Promise<Record<number, number>> {
    const { data } = await api.get<{ counts: Record<number, number> }>(`${BASE}/sorted-out/counts`)
    return data.counts
  },

  async probeQueue(): Promise<QueueStatus> {
    const { data } = await api.post<QueueStatus>(`${BASE}/queue/probe`)
    return data
  },
}

export type ImportClient = typeof importClient
