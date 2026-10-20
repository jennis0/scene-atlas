import { useCallback, useEffect, useState } from 'react'
import type { AppUpdateState, UpdateChoice } from '@/electron'

/**
 * The desktop app's update state, kept current (design/electron.md#updates). The state is
 * undefined outside the desktop app, in a dev build, and until the main process has answered.
 */
export function useAppUpdates() {
  const [state, setState] = useState<AppUpdateState>()

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

  // The main process answers null before the updater has started: keep what we have.
  const check = useCallback(() => {
    void window.electronAPI?.checkForUpdates().then((next) => {
      if (next) setState(next)
    })
  }, [])
  const setChoice = useCallback((choice: UpdateChoice) => {
    void window.electronAPI?.setUpdateChoice(choice).then((next) => {
      if (next) setState(next)
    })
  }, [])
  const download = useCallback(() => {
    void window.electronAPI?.downloadUpdate().then((next) => {
      if (next) setState(next)
    })
  }, [])
  const install = useCallback(() => {
    void window.electronAPI?.installUpdate()
  }, [])
  const openDownload = useCallback(() => {
    void window.electronAPI?.openUpdateDownload()
  }, [])

  return {
    state: state?.status === 'unsupported' ? undefined : state,
    check,
    setChoice,
    download,
    install,
    openDownload,
  }
}
