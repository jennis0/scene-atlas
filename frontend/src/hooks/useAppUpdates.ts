import { useCallback, useEffect, useState } from 'react'
import type { AppUpdateState } from '@/electron'

/**
 * The desktop app's update state, kept current (design/electron.md#updates). The state is
 * null outside the desktop app, in a dev build, and until the main process has answered.
 */
export function useAppUpdates() {
  const [state, setState] = useState<AppUpdateState | null>(null)

  useEffect(() => {
    const api = window.electronAPI
    if (!api) return
    let live = true
    const unsubscribe = api.onUpdateState(setState)
    // A state pushed while this was in flight is newer, so it wins.
    void api.getUpdateState().then((initial) => {
      if (live && initial) setState((current) => current ?? initial)
    })
    return () => {
      live = false
      unsubscribe()
    }
  }, [])

  const keep = useCallback((next: AppUpdateState | null) => {
    if (next) setState(next)
  }, [])
  const check = useCallback(() => {
    void window.electronAPI?.checkForUpdates().then(keep)
  }, [keep])
  const setEnabled = useCallback(
    (enabled: boolean) => {
      void window.electronAPI?.setUpdatesEnabled(enabled).then(keep)
    },
    [keep],
  )
  const install = useCallback(() => {
    void window.electronAPI?.installUpdate()
  }, [])
  const openDownload = useCallback(() => {
    void window.electronAPI?.openUpdateDownload()
  }, [])

  return {
    state: state?.status === 'unsupported' ? null : state,
    check,
    setEnabled,
    install,
    openDownload,
  }
}
