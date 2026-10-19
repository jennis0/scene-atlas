import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { useLibraryInspect } from '@/hooks/useLibraryInspect'
import { useStorageDirs } from '@/hooks/useStorageDirs'
import { libraryApi, type InspectRequest, type InspectResult } from '@/lib/api/libraryApi'
import { ChoiceCard } from './ChoiceCard'
import { LoadFailed } from './LoadFailed'
import { SetupFrame } from './SetupFrame'
import type { StepNav } from './steps'

type Choice = 'new' | 'linked'
type FolderKind = 'appData' | 'store' | 'linked'

/** The store's default place inside a linked folder (design/library-setup.md §1) */
const STORE_IN_LINKED = 'Scene Atlas'

// The one setup text that explains behaviour: linking works differently from importing, and
// users need these four things before choosing it (design/library-setup.md §2.2).
const LINKED_EXPLAINER =
  'Scene Atlas adds the maps and scenes in this folder, and any you add to it later. ' +
  'Tokens and other art are skipped. Your files are never changed, moved or deleted. ' +
  'Maps you import in the app go in the Imported maps folder, not into your own folders.'

/** *name* inside *base*, with the platform's separator */
function joinPath(base: string, name: string): string {
  const sep = window.electronAPI?.platform === 'win32' ? '\\' : '/'
  return `${base.replace(/[\\/]+$/, '')}${sep}${name}`
}

/** "Found 56,214 images." for a maps folder */
function foundText(linked: NonNullable<InspectResult['linked']>): string {
  const count = linked.image_count.toLocaleString()
  return linked.capped ? `Found more than ${count} images.` : `Found ${count} images.`
}

/**
 * Desktop only: where the library lives. Start a new one, or link a folder of maps the
 * user already has; the two storage folders can be moved too. Every set of folders is
 * checked by the backend (POST /library/inspect) before Continue is allowed. Continue hands
 * them to the desktop app, which restarts the backend on them when anything changed; the
 * page then reloads and the wizard resumes after this step.
 */
export function LibraryStep({ nav }: { nav: StepNav }) {
  const { dirs, failed: dirsFailed, reload } = useStorageDirs(true)
  const [choice, setChoice] = useState<Choice>('new')
  const [linked, setLinked] = useState<string | null>(null)
  // Folders the user picked (or a found library's hints filled in); null follows the default
  const [store, setStore] = useState<string | null>(null)
  const [appData, setAppData] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const currentLibraryId = useCurrentLibraryId()

  // Start from the desktop app's config (normally the provisional defaults)
  useEffect(() => {
    if (!dirs) return
    if (dirs.linked) {
      setChoice('linked')
      setLinked(dirs.linked)
    }
    const defaultStore = dirs.linked ? joinPath(dirs.linked, STORE_IN_LINKED) : dirs.defaults.store
    if (dirs.store !== defaultStore) setStore(dirs.store)
    if (dirs.appData !== dirs.defaults.appData) setAppData(dirs.appData)
  }, [dirs])

  const linkedPath = choice === 'linked' ? linked : null
  const defaultStore = linkedPath ? joinPath(linkedPath, STORE_IN_LINKED) : dirs?.defaults.store
  const storePath = store ?? defaultStore ?? null
  const appDataPath = appData ?? dirs?.defaults.appData ?? null

  const request = useMemo<InspectRequest | null>(() => {
    if (!storePath || !appDataPath || (choice === 'linked' && !linkedPath)) return null
    return { app_data: appDataPath, store: storePath, ...(linkedPath && { linked: linkedPath }) }
  }, [appDataPath, storePath, linkedPath, choice])
  const { state: inspect, retry } = useLibraryInspect(request)
  const result = inspect.status === 'done' ? inspect.result : null

  // Another library (not the one this wizard runs on, which has a marker too)
  const found =
    result?.library && currentLibraryId !== undefined
      ? result.library.library_id === currentLibraryId
        ? null
        : result.library
      : null

  // Fill the other folders in from a found library's hints, once per library. Hinted
  // folders follow the user's next choice of folder, so they never pair with another one.
  const hinted = useRef<{ libraryId: string | null; store: boolean; appData: boolean }>({
    libraryId: null,
    store: false,
    appData: false,
  })
  useEffect(() => {
    if (!found || hinted.current.libraryId === found.library_id) return
    const { hints } = found
    hinted.current = { libraryId: found.library_id, store: false, appData: false }
    if (hints.app_data && appData === null && hints.app_data !== appDataPath) {
      setAppData(hints.app_data)
      hinted.current.appData = true
    }
    if (result?.linked?.kind === 'library') {
      // The picked "maps folder" holds a library: point at the library's own linked folder
      // (the user may have picked its "Scene Atlas" subfolder), or open it as it is
      if (!hints.linked) setChoice('new')
      else if (hints.linked !== linkedPath) setLinked(hints.linked)
    } else if (hints.linked && !linkedPath) {
      setChoice('linked')
      setLinked(hints.linked)
    }
    if (hints.store && store === null && hints.store !== storePath) {
      setStore(hints.store)
      hinted.current.store = true
    }
  }, [found, result, appData, appDataPath, store, storePath, linkedPath])

  const clearHints = () => {
    if (hinted.current.store) setStore(null)
    if (hinted.current.appData) setAppData(null)
    hinted.current = { libraryId: null, store: false, appData: false }
  }

  const selectChoice = (next: Choice) => {
    if (next === choice) return
    clearHints()
    setChoice(next)
  }

  const linkFolder = (folder: string) => {
    clearHints()
    setChoice('linked')
    setLinked(folder)
  }

  const pick = async (kind: FolderKind) => {
    const current = { appData: appDataPath, store: storePath, linked }[kind] ?? undefined
    const chosen = await window.electronAPI?.chooseFolder(kind, current)
    if (!chosen) return
    if (kind === 'linked') return linkFolder(chosen)
    if (kind === 'store') {
      hinted.current.store = false
      setStore(chosen)
    } else {
      hinted.current.appData = false
      setAppData(chosen)
    }
  }

  const handleContinue = async () => {
    const api = window.electronAPI
    if (!api || !storePath || !appDataPath) return
    setApplying(true)
    setApplyError(null)
    try {
      const outcome = await api.applyLibrary({
        appData: appDataPath,
        store: storePath,
        linked: linkedPath,
      })
      if (outcome.error) {
        setApplyError(outcome.error)
        setApplying(false)
      } else if (!outcome.restarted) {
        setApplying(false)
        nav.onNext()
      }
      // Restarted: the page reloads, so stay busy until it does
    } catch {
      setApplyError("Couldn't use these folders.")
      setApplying(false)
    }
  }

  const error: ReactNode =
    applyError ??
    (result?.outcome === 'error' ? (result.message ?? "Couldn't use these folders.") : null) ??
    (inspect.status === 'failed' ? (
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
        Couldn&apos;t check these folders.
        <button type="button" onClick={retry} className="font-medium text-primary hover:underline">
          Try again
        </button>
      </span>
    ) : null)

  const linkedNote =
    linkedPath && inspect.status === 'checking'
      ? 'Checking the folder…'
      : result?.linked?.kind === 'maps'
        ? foundText(result.linked)
        : result?.linked?.kind === 'library' && found
          ? 'Scene Atlas library found.'
          : null

  return (
    <SetupFrame
      nav={nav}
      title="Set up your library"
      description="Start a new library, or use a folder of maps you already have."
      primary={{
        onClick: () => void handleContinue(),
        label: found?.setup_completed ? 'Open library' : undefined,
        busy: applying,
        disabled: request === null || result === null || result.outcome === 'error',
      }}
      error={error}
    >
      {dirsFailed && <LoadFailed message="Couldn't load the library folders." onRetry={reload} />}

      {dirs && (
        <fieldset disabled={applying} className="space-y-4 min-w-0">
          <legend className="sr-only">Library folders</legend>
          <div role="radiogroup" aria-label="Library" className="grid grid-cols-1 gap-3">
            <ChoiceCard
              name="setup-library"
              choice={{ value: 'new', label: 'Start a new library' }}
              checked={choice === 'new'}
              onSelect={() => selectChoice('new')}
            />
            <ChoiceCard
              name="setup-library"
              choice={{
                value: 'linked',
                label: 'Use a folder of maps you already have',
                description: choice === 'linked' ? <p>{LINKED_EXPLAINER}</p> : undefined,
                footer:
                  choice === 'linked' ? (
                    <div className="space-y-1.5">
                      <FolderPath
                        path={linked}
                        empty="No folder chosen"
                        action={
                          <Button
                            size="sm"
                            variant="outline"
                            aria-label="Choose a maps folder"
                            onClick={() => void pick('linked')}
                          >
                            Choose
                          </Button>
                        }
                      />
                      <p role="status" className="text-xs text-foreground">
                        {linkedNote}
                      </p>
                    </div>
                  ) : undefined,
              }}
              checked={choice === 'linked'}
              onSelect={() => selectChoice('linked')}
            />
          </div>

          <div className="rounded-lg border border-border/50 bg-card p-4 space-y-4">
            <FolderRow
              label="Imported maps"
              description="Stores full resolution images. It can be stored on any large drive."
              path={storePath}
              onChange={() => void pick('store')}
            />
            <FolderRow
              label="Search data"
              description="Stores metadata and thumbnails. Best on a fast drive."
              path={appDataPath}
              onChange={() => void pick('appData')}
            />
            <StoreNotes
              result={result}
              foundHere={!!found && result?.linked?.kind !== 'library'}
              onUseAsLinked={
                choice === 'new' && storePath
                  ? () => {
                      setStore(null)
                      linkFolder(storePath)
                    }
                  : undefined
              }
            />
          </div>
        </fieldset>
      )}
    </SetupFrame>
  )
}

/** The running library's id, to tell it apart from a library found in the picked folders
 * (the provisional library has a marker too). Undefined until known; null if unknown. */
function useCurrentLibraryId(): string | null | undefined {
  const [id, setId] = useState<string | null | undefined>(undefined)
  useEffect(() => {
    let current = true
    libraryApi.status().then(
      (status) => current && setId(status.library_id),
      () => current && setId(null),
    )
    return () => {
      current = false
    }
  }, [])
  return id
}

function FolderPath({
  path,
  empty,
  action,
}: {
  path: string | null
  empty: string
  action: ReactNode
}) {
  return (
    <div className="flex items-center gap-3">
      <p
        className={`min-w-0 flex-1 text-xs break-all ${path ? 'font-mono text-foreground' : 'text-muted-foreground'}`}
      >
        {path ?? empty}
      </p>
      <div className="shrink-0">{action}</div>
    </div>
  )
}

function FolderRow({
  label,
  description,
  path,
  onChange,
}: {
  label: string
  description: string
  path: string | null
  onChange: () => void
}) {
  return (
    <div className="flex flex-wrap items-start gap-x-4 gap-y-1">
      <p className="w-28 shrink-0 text-sm font-medium pt-1">{label}</p>
      <div className="min-w-0 flex-1 basis-56 space-y-1">
        <FolderPath
          path={path}
          empty="—"
          action={
            <Button
              size="sm"
              variant="outline"
              aria-label={`Change ${label} folder`}
              onClick={onChange}
            >
              Change
            </Button>
          }
        />
        <p className="text-xs text-muted-foreground leading-snug">{description}</p>
      </div>
    </div>
  )
}

/** What the check found about the storage folders: a library, or someone's maps */
function StoreNotes({
  result,
  foundHere,
  onUseAsLinked,
}: {
  result: InspectResult | null
  foundHere: boolean
  onUseAsLinked?: () => void
}) {
  const warning = result && result.outcome !== 'error' ? result.message : null
  const note = foundHere ? 'Scene Atlas library found.' : warning
  // The status stays mounted so changes are announced; with nothing to say it takes no room
  return (
    <div className={note || result?.store_has_maps ? 'space-y-1' : '!mt-0'}>
      <p role="status" className="text-xs text-foreground">
        {note}
      </p>
      {result?.store_has_maps && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-warning">
          This folder already has maps in it.
          {onUseAsLinked && (
            <button
              type="button"
              onClick={onUseAsLinked}
              className="font-medium text-primary hover:underline"
            >
              Use it as your existing folder
            </button>
          )}
        </p>
      )}
    </div>
  )
}
