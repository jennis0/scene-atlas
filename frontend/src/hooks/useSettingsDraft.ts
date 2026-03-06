import { useState, useMemo } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { settingsApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
import type { AppSettings } from '@/types'

export interface UseSettingsDraftReturn {
  settings: AppSettings | undefined
  draft: Partial<AppSettings>
  setField: (key: keyof AppSettings, value: string | number | boolean) => void
  isDirty: boolean
  save: () => Promise<AppSettings>
  discard: () => void
  isSaving: boolean
}

export function useSettingsDraft(): UseSettingsDraftReturn {
  const [draft, setDraft] = useState<Partial<AppSettings>>({})
  const queryClient = useQueryClient()

  // Fetch current settings
  const { data: settings } = useQuery({
    queryKey: [QUERY_KEYS.appSettings],
    queryFn: () => settingsApi.get(),
    staleTime: 30_000,
  })

  // Mutation for saving settings
  const saveMutation = useMutation({
    mutationFn: (partialSettings: Partial<AppSettings>) => settingsApi.patch(partialSettings),
    onSuccess: (updatedSettings) => {
      // Update query cache with full updated settings
      queryClient.setQueryData([QUERY_KEYS.appSettings], updatedSettings)
      // Clear only the fields that were saved from draft
      setDraft((prev) => {
        const newDraft = { ...prev }
        Object.keys(updatedSettings).forEach((key) => {
          delete newDraft[key as keyof AppSettings]
        })
        return newDraft
      })
    },
    onError: (error) => {
      console.error('Failed to save settings:', error)
    },
  })

  const isDirty = useMemo(() => Object.keys(draft).length > 0, [draft])

  const handleSetField = (key: keyof AppSettings, value: string | number | boolean) => {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    return saveMutation.mutateAsync(draft)
  }

  const handleDiscard = () => {
    setDraft({})
  }

  return {
    settings,
    draft,
    setField: handleSetField,
    isDirty,
    save: handleSave,
    discard: handleDiscard,
    isSaving: saveMutation.isPending,
  }
}
