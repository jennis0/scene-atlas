import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useAppUpdates } from '@/hooks/useAppUpdates'
import { useServerUpdates } from '@/hooks/useServerUpdates'
import { readPref, writePref } from '@/lib/prefsStorage'

const TOAST_MS = 20_000
/** Server mode: the last version this browser was told about, so a reload doesn't repeat it */
const ANNOUNCED_UPDATE_KEY = 'scene-atlas-update-announced'

/** Says once per version when an update is ready or out. Settings keeps offering it after
 * the toast has gone. Desktop: from the app's updater; server: from the backend's check,
 * once per browser. */
export function UpdateNotifier() {
  const { state, install, openDownload } = useAppUpdates()
  const server = useServerUpdates()
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

  useEffect(() => {
    if (!server?.update_available || !server.latest_version) return
    const { latest_version: version, release_url: url } = server
    // The ref covers a browser that blocks storage
    if (announced.current.has(version) || readPref(ANNOUNCED_UPDATE_KEY) === version) return
    announced.current.add(version)
    writePref(ANNOUNCED_UPDATE_KEY, version)
    toast.info(`Scene Atlas ${version} is out`, {
      duration: TOAST_MS,
      action: {
        label: 'Release notes',
        onClick: () => window.open(url, '_blank', 'noopener,noreferrer'),
      },
    })
  }, [server])

  return null
}
