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
      'Add your battlemaps, scenes, and encounter art. Drag a folder or use the Import button.',
  },
  {
    Icon: Search,
    title: '2. Search',
    description: 'Find any scene instantly with keywords, tags, or natural-language descriptions.',
  },
  {
    Icon: FolderOpen,
    title: '3. Organize',
    description: 'Images are automatically grouped, tagged, and indexed. Edit anytime.',
  },
]

export function EmptyLibraryWelcome({ embeddingReady, onImport }: EmptyLibraryWelcomeProps) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-lg text-center space-y-8 px-6">
        <div className="space-y-2">
          <h2 className="text-2xl font-bold text-foreground">Welcome to Scene Atlas</h2>
          <p className="text-sm text-muted-foreground">
            Your personal library for tabletop RPG scenes, battlemaps, and encounter art.
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
            <p className="text-xs text-muted-foreground">
              Waiting for AI model to finish loading&hellip;
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
