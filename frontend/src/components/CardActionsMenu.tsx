import { useState, type ReactNode } from 'react'
import { MoreHorizontal, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { downloadFile } from '@/lib/download'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { isAnyDialogOpen } from '@/components/ui/dialogStack'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'

interface CardActionsMenuProps {
  /** Names the trigger: "Actions for {label}" */
  label: string
  /** Items above Download */
  children: ReactNode
  download: { url: string; filename: string; failure: string; icon: ReactNode }
  onDelete?: () => void
}

/**
 * The "..." menu in the top-right corner of a gallery card: the card's own actions, then
 * Download and Delete. The card's root needs the `group/card` class: the trigger shows on
 * hover and on keyboard focus within the card, and always on touch screens.
 */
export function CardActionsMenu({ label, children, download, onDelete }: CardActionsMenuProps) {
  const [downloading, setDownloading] = useState(false)

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (downloading) return
    setDownloading(true)
    try {
      await downloadFile(download.url, download.filename)
    } catch (err) {
      toast.error(getApiErrorMessage(err, download.failure))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="absolute top-2 right-2 z-10">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            data-testid="card-actions-menu"
            aria-label={`Actions for ${label}`}
            className="opacity-0 group-hover/card:opacity-100 group-focus-within/card:opacity-100 [@media(hover:none)]:opacity-100 h-7 w-7 rounded-md flex items-center justify-center bg-black/50 text-white/80 hc:text-white hover:text-white hover:bg-black/70 backdrop-blur-sm transition-all"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          // Leave focus alone when an item opened a dialog: the dialog takes it, and
          // hands it back to this trigger when it closes.
          onCloseAutoFocus={(e) => isAnyDialogOpen() && e.preventDefault()}
        >
          {children}
          <DropdownMenuItem onClick={handleDownload} disabled={downloading}>
            {download.icon}
            {downloading ? 'Downloading…' : 'Download'}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => onDelete?.()}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="h-4 w-4 mr-2" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
