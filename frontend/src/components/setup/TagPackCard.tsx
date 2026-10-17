import { Check, Download } from 'lucide-react'
import type { TagPack } from '@/types'

interface TagPackCardProps {
  pack: TagPack
  onImport: () => void
  isImporting: boolean
}

/**
 * Shared tag pack card used in both the Settings dialog and the setup wizard.
 * Renders pack label, description, tag count, and an import/added button.
 */
export function TagPackCard({ pack, onImport, isImporting }: TagPackCardProps) {
  return (
    <div
      className={`flex items-center justify-between gap-2 rounded border px-3 py-2.5 transition-colors ${
        pack.imported
          ? 'border-border/30 bg-muted/20'
          : 'border-border/50 bg-card hover:border-border'
      }`}
    >
      <div className="min-w-0">
        <p className="text-xs font-medium truncate">{pack.label}</p>
        <p className="text-3xs text-muted-foreground truncate">{pack.description}</p>
        <p className="text-3xs text-muted-foreground mt-0.5">
          {pack.tag_count} tags
          {!pack.imported && pack.new_tags > 0 && (
            <span className="text-primary/70 hc:text-primary"> &middot; {pack.new_tags} new</span>
          )}
        </p>
      </div>
      <button
        type="button"
        disabled={pack.imported || isImporting}
        onClick={onImport}
        aria-label={`Import ${pack.label} tag pack`}
        className={`shrink-0 flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors ${
          pack.imported
            ? 'text-success cursor-default'
            : 'border border-border/50 text-muted-foreground hover:text-foreground hover:border-border disabled:opacity-50'
        }`}
      >
        {pack.imported ? (
          <>
            <Check className="h-3 w-3" />
            <span>Added</span>
          </>
        ) : isImporting ? (
          <span>Importing…</span>
        ) : (
          <>
            <Download className="h-3 w-3" />
            <span>Import</span>
          </>
        )}
      </button>
    </div>
  )
}
