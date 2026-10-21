import { useEffect, useRef, useState } from 'react'
import type { LibraryDirs } from '@/electron'
import { libraryApi, type InspectRequest, type InspectResult } from '@/lib/api/libraryApi'

/** Wait this long after the last change before checking, so quick picks send one request */
export const INSPECT_DEBOUNCE_MS = 150

type InspectState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'done'; result: InspectResult }
  | { status: 'failed' }

function toRequest({ appData, store, linked }: LibraryDirs): InspectRequest {
  return { app_data: appData, store, ...(linked && { linked }) }
}

/**
 * Checks proposed library folders with POST /library/inspect whenever they change (null:
 * nothing to check). Only the latest request's answer is kept: a slow response to an
 * earlier set of folders never overwrites a newer one.
 */
export function useLibraryInspect(dirs: LibraryDirs | null) {
  const key = dirs ? JSON.stringify(toRequest(dirs)) : null
  const [answer, setAnswer] = useState<{ key: string; state: InspectState } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const latest = useRef(0)

  useEffect(() => {
    if (key === null) return
    const id = ++latest.current
    const body = JSON.parse(key) as InspectRequest
    const settle = (state: InspectState) => {
      if (latest.current === id) setAnswer({ key, state })
    }
    const timer = setTimeout(() => {
      libraryApi.inspect(body).then(
        (result) => settle({ status: 'done', result }),
        () => settle({ status: 'failed' }),
      )
    }, INSPECT_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [key, attempt])

  const state: InspectState =
    key === null ? { status: 'idle' } : answer?.key === key ? answer.state : { status: 'checking' }
  const result = state.status === 'done' ? state.result : null
  /** Why the backend refuses these folders, if it does */
  const refusal =
    result?.outcome === 'error' ? (result.message ?? "Couldn't use these folders.") : null
  const retry = () => {
    setAnswer(null)
    setAttempt((n) => n + 1)
  }
  return { state, result, refusal, retry }
}
