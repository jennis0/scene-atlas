import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { systemApi, type ServerUpdateStatus } from '@/lib/api/systemApi'
import { QUERY_KEYS } from '@/lib/queryKeys'

const RELEASES_URL = 'https://github.com/jennis0/scene-atlas/releases'
// The backend checks daily; re-reading its cached answer hourly is cheap.
const REFRESH_MS = 60 * 60 * 1000

/** The backend builds release_url; links still only ever point at our releases. */
function safeReleaseUrl(url: string): string {
  return url === RELEASES_URL || url.startsWith(`${RELEASES_URL}/tag/v`) ? url : RELEASES_URL
}

/**
 * The server's update check (design/backend.md, ADR-022). Undefined in the desktop app,
 * whose updater is useAppUpdates, and until the backend has answered.
 */
export function useServerUpdates(): ServerUpdateStatus | undefined {
  const enabled = typeof window !== 'undefined' && !window.electronAPI
  const { data } = useQuery({
    queryKey: QUERY_KEYS.serverUpdates,
    queryFn: systemApi.getUpdates,
    enabled,
    staleTime: REFRESH_MS,
    refetchInterval: REFRESH_MS,
    retry: false,
  })
  return useMemo(
    () =>
      enabled && data ? { ...data, release_url: safeReleaseUrl(data.release_url) } : undefined,
    [enabled, data],
  )
}
