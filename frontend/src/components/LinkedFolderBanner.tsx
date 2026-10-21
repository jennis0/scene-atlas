import { FolderX } from 'lucide-react'
import { useCheckLinkedFolder } from '@/hooks/useLibraryStatus'
import type { LibraryStatus } from '@/lib/api/libraryApi'

/**
 * Above the gallery while the linked folder is offline (a drive unplugged, a share down):
 * its originals can't be opened, though search, thumbnails and editing all work
 * (design/library-setup.md §4.7).
 */
export function LinkedFolderBanner({ status }: { status: LibraryStatus | undefined }) {
  const check = useCheckLinkedFolder("Couldn't check the linked library.")

  const linked = status?.linked
  if (linked?.state !== 'offline') return null
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-xs text-foreground"
    >
      <span className="flex items-center gap-1.5">
        <FolderX aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-warning" />
        {linked.name} isn&apos;t available
      </span>
      <button
        type="button"
        onClick={() => check.mutate()}
        disabled={check.isPending || linked.scanning}
        className="relative target-24 font-medium text-primary hover:underline disabled:opacity-40"
      >
        Check again
      </button>
    </div>
  )
}
