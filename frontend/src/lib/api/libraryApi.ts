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

  /** Remove the maps whose linked file is missing (never touches files) */
  removeMissing: async (): Promise<{ removed: number }> => {
    const { data } = await api.post<{ removed: number }>('/library/linked/remove-missing')
    return data
  },

  /** "Stop using this folder": remove every map read from it (never touches files) */
  removeLinked: async (): Promise<{ removed: number }> => {
    const { data } = await api.delete<{ removed: number }>('/library/linked')
    return data
  },
}
