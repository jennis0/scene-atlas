import { api } from './_client'

export interface ModelInfo {
  name: string
  label: string
  description: string
  description_technical: string
  recommended_hardware: string // "cpu" | "gpu" | "any"
  approx_size_mb: number
  downloaded: boolean
  version_info: { hf_commit_sha: string; downloaded_at: string } | null
  active: boolean
}

export interface SetupStatus {
  needs_model: boolean
  recommended: string // "small" | "medium" | "large"
  has_gpu: boolean
  gpu_provider: string | null // e.g. "CUDAExecutionProvider" or null
}

export interface EmbeddingStats {
  collection_name: string
  vectors_count: number
  exists: boolean
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

  getEmbeddingStats: async (name: string): Promise<EmbeddingStats> => {
    const { data } = await api.get<EmbeddingStats>(`/models/${name}/embeddings`)
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
}
