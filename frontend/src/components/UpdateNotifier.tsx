import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useAppUpdates } from '@/hooks/useAppUpdates'

const TOAST_MS = 20_000

/**
 * Desktop only. Mounted once setup is finished, so a library set up before the update
 * choice existed (or a wizard left on its default) gets the default here, and only then
 * does the app start checking (design/electron.md#updates).
 *
 * Then says once per version when an update is out or ready; Settings keeps offering it
 * after the toast has gone.
 */
export function UpdateNotifier() {
  const { state, setChoice, download, install, openDownload } = useAppUpdates()
  const announced = useRef(new Set<string>())

  useEffect(() => {
    if (state && !state.choiceMade) setChoice(state.choice)
  }, [state, setChoice])

  useEffect(() => {
    const version = state?.version
    if (!version) return
    const key = `${state.status}:${version}`
    if (announced.current.has(key)) return
    if (state.status === 'ready') {
      announced.current.add(key)
      toast.info(`Scene Atlas ${version} is ready`, {
        description: 'It installs when you quit, or restart now.',
        duration: TOAST_MS,
        action: { label: 'Restart', onClick: install },
      })
    } else if (state.status === 'available') {
      announced.current.add(key)
      toast.info(`Scene Atlas ${version} is out`, {
        duration: TOAST_MS,
        action:
          state.mode === 'install'
            ? { label: 'Update', onClick: download }
            : { label: 'Download', onClick: openDownload },
      })
    }
  }, [state, download, install, openDownload])

  return null
}
