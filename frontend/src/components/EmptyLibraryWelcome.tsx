import { Upload, Search, FolderOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface EmptyLibraryWelcomeProps {
  embeddingReady: boolean
  onImport: () => void
}

const steps = [
  {
    Icon: Upload,
    title: '1. Import',
    description:
      'Drag in a folder, or use the Import button. Scene Atlas keeps its own copy; your files are never changed.',
  },
  {
    Icon: Search,
    title: '2. Search',
    description: 'Find any scene by name, tag, or by describing it in your own words.',
  },
  {
    Icon: FolderOpen,
    title: '3. Organize',
    description: 'Images are grouped and tagged automatically, and you can edit everything.',
  },
]

export function EmptyLibraryWelcome({ embeddingReady, onImport }: EmptyLibraryWelcomeProps) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-lg text-center space-y-8 px-6">
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Your library is empty
          </h2>
          <p className="text-sm text-muted-foreground">
            Import your battlemaps, scenes and encounter art to get started.
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
              Getting the search model ready. If it&rsquo;s downloading, this can take a few
              minutes.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
