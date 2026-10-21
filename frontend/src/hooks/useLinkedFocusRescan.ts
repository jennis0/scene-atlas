import { useEffect, useRef } from 'react'
import { isApp } from '@/lib/appMode'
import { libraryApi, type LibraryStatus } from '@/lib/api/libraryApi'
import { getImportManager } from '@/lib/import/ImportManager'

/** At most one focus rescan a minute from this window; the backend limits it too */
export const FOCUS_RESCAN_INTERVAL_MS = 60_000

/**
 * Desktop app: check the linked folder for changes when the window regains focus, which
 * covers copying maps in with Explorer or Finder and switching back
 * (design/library-setup.md §4.3). Only while the folder is online.
 */
export function useLinkedFocusRescan(status: LibraryStatus | undefined) {
  const online = isApp && status?.linked?.state === 'online'
  const lastScan = useRef(Number.NEGATIVE_INFINITY)

  useEffect(() => {
    if (!online) return
    const handleFocus = () => {
      const now = Date.now()
      if (now - lastScan.current < FOCUS_RESCAN_INTERVAL_MS) return
      lastScan.current = now
      libraryApi
        .scan('focus')
        // A scan that finds files creates an import job: pick it up now, not at the idle poll
        .then(({ started }) => {
          if (started) return getImportManager().refresh()
        })
        .catch(() => {
          // Best effort: the timer rescan catches up
        })
    }
    window.addEventListener('focus', handleFocus)
    return () => window.removeEventListener('focus', handleFocus)
  }, [online])
}
