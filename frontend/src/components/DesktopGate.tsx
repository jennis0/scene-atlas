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

    // Main process signals the backend is ready with its port
    window.electronAPI!.onBackendReady((port: number) => {
      window.__SCENE_ATLAS_PORT__ = port
      startRef.current = Date.now()
      setState({ phase: 'polling', port, elapsed: 0 })

      const interval = setInterval(async () => {
        const elapsed = Math.round((Date.now() - startRef.current) / 1000)
        setState({ phase: 'polling', port, elapsed })

        try {
          const res = await fetch(`http://localhost:${port}/health`)
          if (res.ok) {
            clearInterval(interval)
            setReady(true)
          }
        } catch {
          // Not up yet — keep polling
        }
      }, 1500)

      return () => clearInterval(interval)
    })

    // Main process signals a hard failure (sidecar crashed on startup)
    window.electronAPI!.onBackendError?.((message: string) => {
      setState({ phase: 'error', message })
    })
  }, [isElectron])

  if (ready) return <>{children}</>

  const status = (() => {
    switch (state.phase) {
      case 'waiting-for-signal':
        return 'Starting backend...'
      case 'polling':
        return state.elapsed < 5
          ? `Backend starting on port ${state.port}…`
          : `Loading AI model… (${state.elapsed}s) — first run may take a minute`
      case 'error':
        return `Error: ${state.message}`
    }
  })()

  return <LoadingScreen status={status} isError={state.phase === 'error'} />
}
