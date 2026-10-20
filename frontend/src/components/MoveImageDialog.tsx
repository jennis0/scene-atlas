import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderInput, FolderPlus } from 'lucide-react'
import { toast } from 'sonner'
import { GroupPickerShell } from '@/components/GroupPickerShell'
import { GroupPickerResults, GroupPickerRow } from '@/components/GroupPickerResults'
import { useGroupPickerSearch } from '@/hooks/useGroupPickerSearch'
import { groupApi } from '@/lib/api'
import { fullImageName } from '@/lib/format'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { QUERY_KEYS, invalidateGalleryQueries } from '@/lib/queryKeys'
import type { GroupPickerItem, Image, MoveImagesResponse, MoveTarget } from '@/types'

interface MoveImageDialogProps {
  /** The image to move; the dialog is open while one is set */
  image: Image | null
  onClose: () => void
  onMoved?: (result: MoveImagesResponse) => void
}

type Choice = { kind: 'group'; group: GroupPickerItem } | { kind: 'new' }

/**
 * Moves one image out of its group: into another group, or into a new group of its own,
 * named after the search text or else the image (with its group's name, which import strips
 * from image names). Groups like that name come first.
 */
export function MoveImageDialog({ image, onClose, onMoved }: MoveImageDialogProps) {
  const open = image !== null
  const queryClient = useQueryClient()
  const imageName = image ? fullImageName(image) : ''
  const search = useGroupPickerSearch(open, image?.group_id, imageName)
  const [choice, setChoice] = useState<Choice | null>(null)

  useEffect(() => {
    if (open) setChoice(null)
  }, [open])

  const newGroupName = search.searchQuery.trim() || imageName

  const moveMutation = useMutation({
    mutationFn: ({ image, target }: { image: Image; target: MoveTarget }) =>
      groupApi.moveImages(image.group_id!, target, [image.id]),
    onSuccess: async (result, { image }) => {
      toast.success(`Moved to ${result.target_group_name}`)
      // The open viewer reads the image's group from here: refresh it before closing.
      await queryClient.invalidateQueries({ queryKey: QUERY_KEYS.image(image.id) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.scenes() })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.groupSearches })
      invalidateGalleryQueries(queryClient)
      onMoved?.(result)
      onClose()
    },
    onError: (err) => {
      toast.error(getApiErrorMessage(err, 'Move failed'))
    },
  })

  const confirm = () => {
    if (!image || image.group_id === null || !choice) return
    moveMutation.mutate({
      image,
      target: choice.kind === 'new' ? { newGroupName } : { groupId: choice.group.id },
    })
  }

  return (
    <GroupPickerShell
      open={open}
      onClose={onClose}
      title="Move to Group"
      searchQuery={search.searchQuery}
      onSearchChange={search.setSearchQuery}
      confirmDisabled={!choice || !newGroupName || moveMutation.isPending}
      onConfirm={confirm}
      confirmLabel="Move"
      confirmIcon={<FolderInput className="h-3.5 w-3.5" />}
    >
      <GroupPickerResults
        groups={search.groups}
        isLoading={search.isLoading}
        selectedId={choice?.kind === 'group' ? choice.group.id : null}
        onSelect={(group) => setChoice({ kind: 'group', group })}
        emptyLabel="No other groups found"
        leading={
          <GroupPickerRow
            selected={choice?.kind === 'new'}
            onClick={() => setChoice({ kind: 'new' })}
            icon={<FolderPlus className="h-3.5 w-3.5 text-primary" />}
            title={`New group: ${newGroupName}`}
            subtitle={image?.author}
          />
        }
      />
    </GroupPickerShell>
  )
}
