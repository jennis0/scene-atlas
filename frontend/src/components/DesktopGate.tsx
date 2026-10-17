import { useEffect, useRef, useState } from 'react'
import { LoadingScreen } from './LoadingScreen'

interface DesktopGateProps {
  children: React.ReactNode
}

type GateState =
  | { phase: 'waiting-for-signal' }
  | { phase: 'polling'; port: number; elapsed: number }
  | { phase: 'error'; message: string }

export function DesktopGate({ children }: DesktopGateProps) {
  const isElectron = typeof window !== 'undefined' && !!window.electronAPI
  const [ready, setReady] = useState(!isElectron)
  const [state, setState] = useState<GateState>({ phase: 'waiting-for-signal' })
  const startRef = useRef<number>(0)

  useEffect(() => {
    if (!isElectron) return

    // cancelled = true when this effect instance is cleaned up (e.g. React
    // StrictMode double-invocation).  Any IPC callbacks that fire after cleanup
    // check this flag and bail out, ensuring only one polling loop is active.
    let cancelled = false
    let started = false
    let timeoutId: ReturnType<typeof setTimeout> | null = null

    // Main process signals the backend is ready with its port. It re-sends on
    // every page load, so ignore repeats once polling has started.
    const offReady = window.electronAPI!.onBackendReady((port: number) => {
      if (cancelled || started) return
      started = true
      Object.defineProperty(window, '__SCENE_ATLAS_PORT__', {
        value: port,
        writable: false,
        configurable: true,
      })
      startRef.current = Date.now()
      setState({ phase: 'polling', port, elapsed: 0 })

      // Recursive setTimeout — next poll only starts after the current fetch
      // completes, preventing request pile-up when the backend is slow to respond.
      const poll = async () => {
        if (cancelled) return
        const elapsed = Math.round((Date.now() - startRef.current) / 1000)
        setState({ phase: 'polling', port, elapsed })
        try {
          const res = await fetch(`http://localhost:${port}/health`)
          if (res.ok) {
            setReady(true)
            return // Stop polling — backend is up
          }
        } catch {
          // Not up yet — schedule next attempt
        }
        if (!cancelled) timeoutId = setTimeout(poll, 100)
      }

      timeoutId = setTimeout(poll, 100)
    })

    // Main process signals a hard failure (sidecar crashed on startup)
    const offError = window.electronAPI!.onBackendError?.((message: string) => {
      if (!cancelled) setState({ phase: 'error', message })
    })

    return () => {
      cancelled = true
      if (timeoutId) clearTimeout(timeoutId)
      offReady?.()
      offError?.()
    }
  }, [isElectron])

  if (ready) return <>{children}</>

  const { status, errorDetail } = (() => {
    switch (state.phase) {
      case 'waiting-for-signal':
        return { status: 'Starting up', errorDetail: undefined }
      case 'polling': {
        const msg =
          state.elapsed < 8
            ? 'Starting up'
            : state.elapsed < 25
              ? 'Loading resources'
              : 'First launch takes a little longer than usual'
        return { status: msg, errorDetail: undefined }
      }
      case 'error':
        return { status: "Couldn't start Scene Atlas", errorDetail: state.message }
    }
  })()

  return (
    <LoadingScreen status={status} isError={state.phase === 'error'} errorDetail={errorDetail} />
  )
}
