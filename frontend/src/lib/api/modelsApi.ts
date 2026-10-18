import { api } from './_client'

export interface ModelInfo {
  name: string
  label: string
  description: string
  description_technical: string
  recommended_hardware: string // "cpu" | "gpu" | "any"
  approx_size_mb: number
  /** Indicative image processing speed out of 5, without and with a GPU */
  speed: { cpu: number; gpu: number }
  /** Indicative search quality out of 5 */
  search_quality: number
  downloaded: boolean
  version_info: { hf_commit_sha: string; downloaded_at: string } | null
  active: boolean
}

export interface SetupStatus {
  needs_model: boolean
  /** The first-run wizard has been finished */
  setup_completed: boolean
  /** A model download/activation is queued or running */
  model_activating: boolean
  recommended: string // "small" | "medium" | "large"
  has_gpu: boolean
  gpu_provider: string | null // e.g. "CUDAExecutionProvider" or null
}

export const modelsApi = {
  list: async (): Promise<{ models: ModelInfo[] }> => {
    const { data } = await api.get<{ models: ModelInfo[] }>('/models/')
    return data
  },

  setupStatus: async (): Promise<SetupStatus> => {
    const { data } = await api.get<SetupStatus>('/models/setup-status')
    return data
  },

  downloadModel: async (name: string): Promise<{ status: string; job_id: string | null }> => {
    const { data } = await api.post<{ status: string; job_id: string | null }>(
      `/models/${name}/download`,
    )
    return data
  },

  setActiveModel: async (modelName: string): Promise<{ status: string; job_id: string | null }> => {
    const { data } = await api.post<{ status: string; job_id: string | null }>('/models/active', {
      model_name: modelName,
    })
    return data
  },

  deleteEmbeddings: async (name: string): Promise<void> => {
    await api.delete(`/models/${name}/embeddings`)
  },

  embeddingStatus: async (): Promise<{ status: string; error: string | null }> => {
    const { data } = await api.get<{ status: string; error: string | null }>(
      '/models/embedding-status',
    )
    return data
  },

  setupComplete: async (): Promise<void> => {
    await api.post('/models/setup-complete')
  },
}
