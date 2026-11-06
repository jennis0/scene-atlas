import { Upload, Search, FolderOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ProgressSummary } from '@/components/imports/ImportProgress'
import type { ImportJobSummary } from '@/lib/import/types'

interface EmptyLibraryWelcomeProps {
  embeddingReady: boolean
  /** A scan of the linked folder is running: say so in place of the import prompt */
  addingMaps?: boolean
  /** The linked folder's import, once the scan has made one: its progress is shown */
  linkedJob?: ImportJobSummary
  secondsPerItem?: number | null
  onImport: () => void
}

const steps = [
  {
    Icon: Upload,
    title: '1. Import',
    description: 'Use the Import button, then drop in a folder or files.',
  },
  {
    Icon: Search,
    title: '2. Search',
    description: 'Find any scene by name, tag, or by describing it in your own words.',
  },
  {
    Icon: FolderOpen,
    title: '3. Organize',
    description: 'Images are grouped and tagged automatically. Edit anything.',
  },
]

export function EmptyLibraryWelcome({
  embeddingReady,
  addingMaps = false,
  linkedJob,
  secondsPerItem,
  onImport,
}: EmptyLibraryWelcomeProps) {
  if (addingMaps)
    return (
      <AddingMaps embeddingReady={embeddingReady} job={linkedJob} secondsPerItem={secondsPerItem} />
    )
  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-lg text-center space-y-8 px-6">
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Your library is empty
          </h2>
          <p className="text-sm text-muted-foreground">
            Import your battlemaps, scenes and encounter art.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {steps.map(({ Icon, title, description }) => (
            <div
              key={title}
              className="rounded-lg border border-border bg-card p-4 space-y-2 text-left"
            >
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10">
                  <Icon className="h-3.5 w-3.5 text-primary" />
                </div>
                <span className="text-sm font-semibold text-foreground">{title}</span>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">{description}</p>
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <Button onClick={onImport} disabled={!embeddingReady} className="gap-1.5">
            <Upload className="h-4 w-4" />
            Import your first scenes
          </Button>
          {!embeddingReady && (
            <p role="status" className="text-xs text-muted-foreground">
              Getting the search model ready&hellip;
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

/** The first scan of a linked folder. Its images are listed only once the whole import is
 * grouped (ADR-028), so this screen stays until then and shows the import's progress. The one
 * place that says a large folder takes hours (design/library-setup.md §2.3). */
function AddingMaps({
  embeddingReady,
  job,
  secondsPerItem,
}: {
  embeddingReady: boolean
  job?: ImportJobSummary
  secondsPerItem?: number | null
}) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-md text-center space-y-6 px-6">
        {/* The live region leaves out the progress line, which changes every few seconds */}
        <div role="status" className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Adding your images&hellip;
          </h2>
          <p className="text-sm text-muted-foreground">
            They appear here once they&apos;re all added and grouped. A large folder can take a few
            hours.
          </p>
          {!embeddingReady && (
            <p className="text-xs text-muted-foreground">Getting the search model ready&hellip;</p>
          )}
        </div>
        {job && (
          <div className="text-left">
            <ProgressSummary job={job} secondsPerItem={secondsPerItem} />
          </div>
        )}
      </div>
    </div>
  )
}
