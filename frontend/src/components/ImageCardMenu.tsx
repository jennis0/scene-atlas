import { Download, FolderInput, Pencil } from 'lucide-react'
import { CardActionsMenu } from '@/components/CardActionsMenu'
import { DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { getImageUrl } from '@/lib/api'
import { imageDownloadFilename } from '@/lib/download'
import { fullImageName } from '@/lib/format'
import type { Image } from '@/types'

export interface ImageCardActions {
  onEditGroup: (image: Image) => void
  onMove: (image: Image) => void
  onDelete: (image: Image) => void
}

/** The "..." menu on an image in the individual view: its group's editor, move, download, delete. */
export function ImageCardMenu({ image, actions }: { image: Image; actions: ImageCardActions }) {
  const inGroup = image.group_id !== null
  return (
    <CardActionsMenu
      label={fullImageName(image)}
      download={{
        url: getImageUrl(image),
        filename: imageDownloadFilename(image),
        failure: 'Download failed',
        icon: <Download className="h-4 w-4 mr-2" />,
      }}
      onDelete={() => actions.onDelete(image)}
    >
      {inGroup && (
        <DropdownMenuItem onClick={() => actions.onEditGroup(image)}>
          <Pencil className="h-4 w-4 mr-2" />
          Edit group
        </DropdownMenuItem>
      )}
      {inGroup && (
        <DropdownMenuItem onClick={() => actions.onMove(image)}>
          <FolderInput className="h-4 w-4 mr-2" />
          Move to group…
        </DropdownMenuItem>
      )}
    </CardActionsMenu>
  )
}
