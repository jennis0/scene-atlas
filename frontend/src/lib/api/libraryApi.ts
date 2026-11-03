import { api } from './_client'

// The library's folders and its linked folder (design/library-setup.md "Interfaces between
// the parts"). Folder paths are never set through the API: the desktop app applies them
// over IPC (electronAPI.applyLibrary).

/** What Continue would do with the proposed folders */
export type InspectOutcome = 'new' | 'open' | 'error'

/** POST /library/inspect (desktop app only; 404 on servers) */
export interface InspectRequest {
  app_data?: string
  store?: string
  linked?: string
}

export interface InspectResult {
  outcome: InspectOutcome
  /** Set for 'error' (the refusal) and for warnings */
  message: string | null
  /** Present when `linked` was sent */
  linked: null | {
    /** 'library': the folder or its "Scene Atlas" subfolder holds a store marker */
    kind: 'maps' | 'empty' | 'library'
    /** Supported images found (0 for 'library') */
    image_count: number
    /** Counting stopped at max_local_import_items */
    capped: boolean
  }
  /** A Scene Atlas library found in any of the sent folders */
  library: null | {
    library_id: string
    /** Null when its app data wasn't found */
    setup_completed: boolean | null
    /** Absolute, resolved */
    hints: { app_data: string | null; store: string | null; linked: string | null }
  }
  /** The `store` folder holds files that aren't Scene Atlas's */
  store_has_maps: boolean
}

export interface LinkedFolder {
  state: 'online' | 'offline' | 'detached'
  /** The folder's base name, shown in both modes */
  name: string
  /** Only in the desktop app; never on servers */
  path: string | null
  image_count: number
  missing_count: number
  /** ISO */
  last_scan_at: string | null
  scanning: boolean
}

export interface LibraryStatus {
  library_id: string
  linked: LinkedFolder | null
}

export interface FullExportStatus {
  job_id: string | null
  folder: string // server: where exports go; desktop: ''
  latest: string | null // server: the newest export's folder
}

/** A list of images by group, as a rebuild's check reports it */
export interface RebuildListed {
  images: number
  group_count: number
  groups: { name: string; images: string[] }[]
}

/** What checking an export found (design/export-backup-move.md §8.2) */
export interface RebuildCheck {
  images: number
  groups: number
  created_at: string
  app_version: string
  different_library: boolean
  reembed: boolean
  linked_checked: boolean
  missing: RebuildListed
  lost: RebuildListed
  missing_stored: number
  linked_missing: number
  linked_lost: number
}

export interface RebuildStatus {
  staged: boolean
  check: RebuildCheck | null
  check_error: string | null
  built: boolean
  job_id: string | null
  summary: { id: string; moved: number; folder: string | null } | null
  set_aside_running: boolean
}

export const libraryApi = {
  inspect: async (body: InspectRequest): Promise<InspectResult> => {
    const { data } = await api.post<InspectResult>('/library/inspect', body)
    return data
  },

  status: async (): Promise<LibraryStatus> => {
    const { data } = await api.get<LibraryStatus>('/library/status')
    return data
  },

  /** `focus` is ignored if a scan ran in the last minute, or when rescans are off */
  scan: async (reason: 'manual' | 'focus'): Promise<{ started: boolean }> => {
    const { data } = await api.post<{ started: boolean }>('/library/scan', { reason })
    return data
  },

  /** The export running now, and (on a server) the newest one waiting to be downloaded */
  metadataExportStatus: async (): Promise<{ job_id: string | null; latest: string | null }> => {
    const { data } = await api.get<{ job_id: string | null; latest: string | null }>(
      '/library/metadata-export',
    )
    return data
  },

  /** Export the library's metadata as a background job (design/export-backup-move.md §4).
   * The desktop app passes the file it picked; a server writes it for download. */
  startMetadataExport: async (path?: string): Promise<{ job_id: string }> => {
    const { data } = await api.post<{ job_id: string }>('/library/metadata-export', { path })
    return data
  },

  /** The library export running now; on a server, where exports go and the newest one */
  fullExportStatus: async (): Promise<FullExportStatus> => {
    const { data } = await api.get<FullExportStatus>('/library/full-export')
    return data
  },

  /** Export every image and its metadata as a folder (design/export-backup-move.md §7).
   * The desktop app passes the folder it picked; a server writes into its exports folder,
   * carrying on its newest export with `resume`. */
  startFullExport: async (options: {
    path?: string
    resume?: boolean
    includeLinked?: boolean
  }): Promise<{ job_id: string; path: string }> => {
    const { data } = await api.post<{ job_id: string; path: string }>('/library/full-export', {
      path: options.path,
      resume: options.resume ?? false,
      include_linked: options.includeLinked ?? true,
    })
    return data
  },

  /** Move library (desktop app; design/export-backup-move.md §10) */
  moveStatus: async (): Promise<{
    job_id: string | null
    moved_from: Record<string, string> | null
  }> => {
    const { data } = await api.get('/library/move')
    return data
  },

  /** Copy the folders while the app runs; the job's result is the new folders */
  startMove: async (moved: { app_data?: string; store?: string }): Promise<{ job_id: string }> => {
    const { data } = await api.post<{ job_id: string }>('/library/move', moved)
    return data
  },

  deleteMovedFrom: async (): Promise<{ deleted: number }> => {
    const { data } = await api.delete<{ deleted: number }>('/library/move/old')
    return data
  },

  /** Rebuild from a metadata export (design/export-backup-move.md §8) */
  rebuildStatus: async (): Promise<RebuildStatus> => {
    const { data } = await api.get<RebuildStatus>('/library/rebuild')
    return data
  },

  uploadRebuild: async (file: File, onProgress?: (loaded: number) => void): Promise<void> => {
    await api.put('/library/rebuild/upload', file, {
      headers: { 'Content-Type': 'application/octet-stream' },
      timeout: 0,
      onUploadProgress: (e) => onProgress?.(e.loaded),
    })
  },

  checkRebuild: async (): Promise<{ job_id: string }> => {
    const { data } = await api.post<{ job_id: string }>('/library/rebuild/check', {})
    return data
  },

  buildRebuild: async (): Promise<{ job_id: string }> => {
    const { data } = await api.post<{ job_id: string }>('/library/rebuild/build', {})
    return data
  },

  /** Swap the built library in: the desktop app restarts its backend; a server stops and
   * its service manager starts it again */
  applyRebuild: async (): Promise<{ restart: 'app' | 'server' }> => {
    const { data } = await api.post<{ restart: 'app' | 'server' }>('/library/rebuild/apply', {})
    return data
  },

  cancelRebuild: async (): Promise<void> => {
    await api.delete('/library/rebuild')
  },

  /** Remove the maps whose linked file is missing (never touches files) */
  removeMissing: async (): Promise<{ removed: number }> => {
    const { data } = await api.post<{ removed: number }>('/library/linked/remove-missing')
    return data
  },

  /** "Unlink": remove every map read from it (never touches files) */
  removeLinked: async (): Promise<{ removed: number }> => {
    const { data } = await api.delete<{ removed: number }>('/library/linked')
    return data
  },
}
