import { api } from './_client'
import type { Tag, TagCategory, TagPack, TagValue, TagStats } from '@/types'

export const tagApi = {
  // ── Category CRUD ──────────────────────────────────────────────────────

  getCategories: async (): Promise<TagCategory[]> => {
    const { data } = await api.get<TagCategory[]>('/tags/categories')
    return data
  },

  getCategory: async (category: string): Promise<TagCategory> => {
    const { data } = await api.get<TagCategory>(`/tags/categories/${category}`)
    return data
  },

  createCategory: async (payload: {
    name: string
    description?: string
    color?: string
    icon?: string | null
    display_order?: number
  }): Promise<TagCategory> => {
    const { data } = await api.post<TagCategory>('/tags/categories', payload)
    return data
  },

  updateCategory: async (
    categoryName: string,
    payload: {
      name?: string
      description?: string
      color?: string
      icon?: string | null
      display_order?: number
    },
  ): Promise<{ category: TagCategory; affected_images: number }> => {
    const { data } = await api.patch(`/tags/categories/${categoryName}`, payload)
    return data
  },

  deleteCategory: async (
    categoryName: string,
  ): Promise<{ deleted_tags: number; affected_images: number }> => {
    const { data } = await api.delete(`/tags/categories/${categoryName}`)
    return data
  },

  // ── Tag value management within categories ─────────────────────────────

  upsertTagValue: async (
    categoryName: string,
    tagName: string,
    aliases?: string[],
  ): Promise<TagCategory> => {
    const { data } = await api.put<TagCategory>(
      `/tags/categories/${categoryName}/tags/${tagName}`,
      aliases ?? [],
    )
    return data
  },

  renameTagValue: async (
    categoryName: string,
    tagName: string,
    newValue: string,
  ): Promise<{
    category: TagCategory
    old_value: string
    new_value: string
    affected_images: number
  }> => {
    const { data } = await api.patch(`/tags/categories/${categoryName}/tags/${tagName}`, {
      new_value: newValue,
    })
    return data
  },

  deleteTagValue: async (
    categoryName: string,
    tagName: string,
  ): Promise<{ deleted_tags: number; affected_images: number }> => {
    const { data } = await api.delete(`/tags/categories/${categoryName}/tags/${tagName}`)
    return data
  },

  // ── Per-image tag operations ───────────────────────────────────────────

  getValues: async (category: string): Promise<TagValue[]> => {
    const { data } = await api.get<TagValue[]>(`/tags/values/${category}`)
    return data
  },

  getStats: async (): Promise<TagStats> => {
    const { data } = await api.get<TagStats>('/tags/stats')
    return data
  },

  addToImage: async (imageId: number, tag: { category: string; value: string }): Promise<Tag> => {
    const { data } = await api.post<Tag>(`/tags/image/${imageId}`, {
      ...tag,
      confidence: 1.0,
      source: 'manual',
    })
    return data
  },

  removeTag: async (tagId: number): Promise<void> => {
    await api.delete(`/tags/${tagId}`)
  },

  retagAll: async (): Promise<{ job_id: string; message: string }> => {
    const { data } = await api.post('/tags/retag-all')
    return data
  },

  // ── Tag Packs ─────────────────────────────────────────────────────────

  getTagPacks: async (): Promise<TagPack[]> => {
    const { data } = await api.get<TagPack[]>('/tags/packs')
    return data
  },

  importTagPack: async (
    packName: string,
  ): Promise<{ categories_created: number; tags_added: number; tags_existing: number }> => {
    const { data } = await api.post(`/tags/packs/${packName}/import`)
    return data
  },
}
