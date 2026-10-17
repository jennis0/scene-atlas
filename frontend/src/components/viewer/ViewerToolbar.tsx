import { useState } from 'react'
import { Download, Edit, FolderDown, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { getGroupDownloadUrl, getImageUrl } from '@/lib/api'
import { downloadFile, imageDownloadFilename } from '@/lib/download'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import type { Image } from '@/types'

const TEXT_ACTION =
  'relative target-24 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors'
const ICON_ACTION = 'h-7 w-7 rounded flex items-center justify-center text-muted-foreground'

interface ViewerToolbarProps {
  image: Image
  onEditGroup?: (groupId: number) => void
  onDelete: () => void
  onClose: () => void
}

export function ViewerToolbar({ image, onEditGroup, onDelete, onClose }: ViewerToolbarProps) {
  const [downloading, setDownloading] = useState(false)
  const [downloadingGroup, setDownloadingGroup] = useState(false)

  const download = async (
    url: string,
    filename: string,
    setBusy: (busy: boolean) => void,
    failure: string,
  ) => {
    setBusy(true)
    try {
      await downloadFile(url, filename)
    } catch (err) {
      toast.error(getApiErrorMessage(err, failure))
    } finally {
      setBusy(false)
    }
  }

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
              download(
                getGroupDownloadUrl(image.group_id!),
                `${image.group_name ?? 'Group'}.zip`,
                setDownloadingGroup,
                'Group download failed',
              )
            }
            disabled={downloadingGroup}
            className={`${TEXT_ACTION} disabled:opacity-40`}
          >
            <FolderDown className="h-3.5 w-3.5" />
            Download group
          </button>
        )}
      </div>
      <div className="flex items-center gap-0.5">
        <button
          onClick={() =>
            download(
              getImageUrl(image),
              imageDownloadFilename(image),
              setDownloading,
              'Download failed',
            )
          }
          disabled={downloading}
          title="Download image"
          className={`${ICON_ACTION} hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-40`}
        >
          <Download className="h-4 w-4" />
        </button>
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
