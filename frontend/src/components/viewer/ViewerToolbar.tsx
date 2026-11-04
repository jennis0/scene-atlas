import { Download, Edit, FolderDown, FolderInput, Trash2, X } from 'lucide-react'
import { getImageDownloadUrl } from '@/lib/api'
import { saveUrl } from '@/lib/download'
import { useDownload } from '@/hooks/useDownload'
import type { Image } from '@/types'

const TEXT_ACTION =
  'relative target-24 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors'
const ICON_ACTION = 'h-7 w-7 rounded flex items-center justify-center text-muted-foreground'

interface ViewerToolbarProps {
  image: Image
  onEditGroup?: (groupId: number) => void
  /** Move the image to another group */
  onMove: () => void
  onDelete: () => void
  onClose: () => void
}

export function ViewerToolbar({
  image,
  onEditGroup,
  onMove,
  onDelete,
  onClose,
}: ViewerToolbarProps) {
  const groupDownload = useDownload()

  return (
    <div className="flex items-center justify-between mb-1.5">
      <div className="flex items-center gap-3">
        {image.group_id !== null && onEditGroup && (
          <button onClick={() => onEditGroup(image.group_id!)} className={TEXT_ACTION}>
            <Edit className="h-3.5 w-3.5" />
            Edit group
          </button>
        )}
        {image.group_id !== null && (
          <button
            onClick={() =>
              void groupDownload.download({ group_ids: [image.group_id!] }, 'Group download failed')
            }
            disabled={groupDownload.busy}
            className={`${TEXT_ACTION} disabled:opacity-40`}
          >
            <FolderDown className="h-3.5 w-3.5" />
            Download group
          </button>
        )}
      </div>
      <div className="flex items-center gap-0.5">
        <button
          onClick={() => saveUrl(getImageDownloadUrl(image), '')}
          disabled={image.file_state !== 'ok'}
          aria-label="Download image"
          title={image.file_state === 'ok' ? 'Download image' : "The original file can't be read"}
          className={`${ICON_ACTION} hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-40`}
        >
          <Download className="h-4 w-4" />
        </button>
        {image.group_id !== null && (
          <button
            onClick={onMove}
            title="Move to another group"
            className={`${ICON_ACTION} hover:text-foreground hover:bg-secondary transition-colors`}
          >
            <FolderInput className="h-4 w-4" />
          </button>
        )}
        <button
          onClick={onDelete}
          title="Delete image"
          className={`${ICON_ACTION} hover:text-destructive hover:bg-destructive/10 transition-colors`}
        >
          <Trash2 className="h-4 w-4" />
        </button>
        <div className="w-px h-4 bg-border/40 mx-0.5" />
        <button
          onClick={onClose}
          title="Close"
          className={`${ICON_ACTION} hover:text-foreground hover:bg-secondary transition-colors`}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
