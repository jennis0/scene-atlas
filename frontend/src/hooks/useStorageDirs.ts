import { useCallback, useEffect, useState } from 'react'
import type { StorageDirs } from '@/electron'

/** The desktop app's configured folders; null outside the desktop app, until loaded, or
 * when they couldn't be read. */
export function useStorageDirs(enabled: boolean) {
  const [dirs, setDirs] = useState<StorageDirs | null>(null)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const api = window.electronAPI
    if (!enabled || !api) return
    let current = true
    setFailed(false)
    api
      .getStorageDirs()
      .then((loaded) => current && setDirs(loaded))
      .catch(() => current && setFailed(true))
    return () => {
      current = false
    }
  }, [enabled, attempt])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])

  return { dirs, failed, reload }
}
