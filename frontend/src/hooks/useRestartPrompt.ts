import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import type { RestartPromptProps } from '@/components/settings/RestartBadge'
import { settingsApi } from '@/lib/api/settingsApi'
import { QUERY_KEYS } from '@/lib/queryKeys'
import type { AppSettings } from '@/types'

interface Options {
  enabled: boolean
  settings: AppSettings | undefined
  draft: Partial<AppSettings>
  /** Save the draft, so a restart applies it */
  save: () => Promise<unknown>
}

/**
 * The restart prompt for settings the backend reads only at startup. A setting is pending
 * when the draft changes it, or when its saved value isn't the one the running backend
 * started with (GET /settings/restart-pending: it may have been changed elsewhere).
 * The desktop app saves, then restarts its backend; a server can't restart itself.
 */
export function useRestartPrompt({ enabled, settings, draft, save }: Options) {
  const { data: pendingKeys } = useQuery({
    queryKey: QUERY_KEYS.restartPending,
    queryFn: () => settingsApi.restartPending(),
    enabled,
  })
  const [restarting, setRestarting] = useState(false)
  const desktop = typeof window !== 'undefined' && !!window.electronAPI

  const restartNow = async () => {
    setRestarting(true)
    try {
      await save()
    } catch {
      toast.error('Failed to save settings')
      setRestarting(false)
      return
    }
    // Resolves only when the app can't restart its backend (dev); otherwise the page reloads
    if (!(await window.electronAPI?.restartBackend())) {
      setRestarting(false)
      toast.info('Restart the backend to apply this.')
    }
  }

  return (key: keyof AppSettings): RestartPromptProps => ({
    pending: (key in draft && draft[key] !== settings?.[key]) || !!pendingKeys?.includes(key),
    onRestart: desktop ? () => void restartNow() : undefined,
    restarting,
  })
}
