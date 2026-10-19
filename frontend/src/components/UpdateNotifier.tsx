import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useAppUpdates } from '@/hooks/useAppUpdates'

const TOAST_MS = 20_000

/** Desktop only: says once per version when an update is ready or out. Settings keeps
 * offering it after the toast has gone. */
export function UpdateNotifier() {
  const { state, install, openDownload } = useAppUpdates()
  const announced = useRef(new Set<string>())

  useEffect(() => {
    const version = state?.version
    if (!version || announced.current.has(version)) return
    if (state.status === 'ready') {
      announced.current.add(version)
      toast.info(`Scene Atlas ${version} is ready`, {
        description: 'It installs when you quit, or restart now.',
        duration: TOAST_MS,
        action: { label: 'Restart', onClick: install },
      })
    } else if (state.status === 'available') {
      announced.current.add(version)
      toast.info(`Scene Atlas ${version} is out`, {
        duration: TOAST_MS,
        action: { label: 'Download', onClick: openDownload },
      })
    }
  }, [state, install, openDownload])

  return null
}
