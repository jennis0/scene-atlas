import { useEffect, useState } from 'react'

/** Electron's configured storage directories; both null outside Electron or until loaded. */
export function useStorageDirs(enabled: boolean) {
  const [appDataDir, setAppDataDir] = useState<string | null>(null)
  const [imageLibraryDir, setImageLibraryDir] = useState<string | null>(null)

  useEffect(() => {
    const api = window.electronAPI
    if (!enabled || !api) return
    api.getAppDataDir().then(setAppDataDir)
    api.getImageLibraryDir().then(setImageLibraryDir)
  }, [enabled])

  return { appDataDir, imageLibraryDir }
}
