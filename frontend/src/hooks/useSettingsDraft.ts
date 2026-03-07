import { useState, useMemo, useCallback } from 'react'
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
  isLoading: boolean
  isError: boolean
  error: Error | null
}

interface UseSettingsDraftOptions {
  enabled?: boolean
}

export function useSettingsDraft(options?: UseSettingsDraftOptions): UseSettingsDraftReturn {
  const [draft, setDraft] = useState<Partial<AppSettings>>({})
  const queryClient = useQueryClient()
  const { enabled = true } = options || {}

  // Fetch current settings (with optional enabled flag for lazy-loading)
  const {
    data: settings,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: QUERY_KEYS.appSettings,
    queryFn: () => settingsApi.get(),
    staleTime: 30_000,
    enabled,
  })

  // Mutation for saving settings
  const saveMutation = useMutation({
    mutationFn: (partialSettings: Partial<AppSettings>) => settingsApi.patch(partialSettings),
    onSuccess: (updatedSettings) => {
      // Update query cache with full updated settings
      queryClient.setQueryData(QUERY_KEYS.appSettings, updatedSettings)
      // Clear entire draft on successful save. Race-condition edits are intentionally discarded
      // (user edits made while mutation in-flight are lost, but this is acceptable UX)
      setDraft({})
    },
    onError: (error) => {
      console.error('Failed to save settings:', error)
    },
  })

  const isDirty = useMemo(() => Object.keys(draft).length > 0, [draft])

  const handleSetField = useCallback((key: keyof AppSettings, value: string | number | boolean) => {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleSave = useCallback(() => saveMutation.mutateAsync(draft), [draft, saveMutation])

  const handleDiscard = useCallback(() => {
    setDraft({})
  }, [])

  return {
    settings,
    draft,
    setField: handleSetField,
    isDirty,
    save: handleSave,
    discard: handleDiscard,
    isSaving: saveMutation.isPending,
    isLoading,
    isError,
    error: error as Error | null,
  }
}
