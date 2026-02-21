import { Check } from 'lucide-react'

interface ImportDonePaneProps {
  completedCount: number
  onClose: () => void
}

export function ImportDonePane({ completedCount, onClose }: ImportDonePaneProps) {
  return (
    <div className="flex flex-col items-center py-10 gap-4 px-6">
      <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center">
        <Check className="h-7 w-7 text-primary" />
      </div>
      <div className="text-center">
        <p className="font-display text-xl font-semibold text-foreground">All done</p>
        <p className="text-sm text-muted-foreground mt-1">
          {completedCount} group{completedCount !== 1 ? 's' : ''} imported successfully.
        </p>
      </div>
      <button
        onClick={onClose}
        className="px-4 py-2 text-sm rounded border border-primary/40 bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
      >
        Close
      </button>
    </div>
  )
}
