import { useState, useEffect } from 'react'
import { useQueryClient, useMutation } from '@tanstack/react-query'
import { GroupPickerShell } from '@/components/GroupPickerShell'
import { GroupPickerResults } from '@/components/GroupPickerResults'
import { useGroupPickerSearch } from '@/hooks/useGroupPickerSearch'
import { groupApi } from '@/lib/api'
import { QUERY_KEYS, invalidateGalleryQueries } from '@/lib/queryKeys'
import type { GroupPickerItem } from '@/types'

interface MergeGroupPickerProps {
  open: boolean
  onClose: () => void
  sourceGroupId?: number | null
  excludeGroupId?: number | null
  onSelect?: (targetGroup: GroupPickerItem) => void
  onMergeComplete?: () => void
  title?: string
  currentGroupName?: string
}

export function MergeGroupPicker({
  open,
  onClose,
  sourceGroupId,
  excludeGroupId,
  onSelect,
  onMergeComplete,
  title = 'Merge into Group',
  currentGroupName,
}: MergeGroupPickerProps) {
  const queryClient = useQueryClient()
  const search = useGroupPickerSearch(open, excludeGroupId, currentGroupName)
  const [selected, setSelected] = useState<GroupPickerItem | null>(null)

  const mergeMutation = useMutation({
    mutationFn: (targetGroup: GroupPickerItem) => groupApi.merge(sourceGroupId!, targetGroup.id),
    onSuccess: async (_, targetGroup) => {
      // Wait for search gallery to update before closing, so user sees fresh data
      await queryClient.refetchQueries({ queryKey: QUERY_KEYS.search })
      invalidateGalleryQueries(queryClient)
      onMergeComplete?.()
      onSelect?.(targetGroup)
      onClose()
    },
    onError: (err) => {
      console.error('Failed to merge groups:', err)
    },
  })

  useEffect(() => {
    if (open) setSelected(null)
  }, [open])

  return (
    <GroupPickerShell
      open={open}
      onClose={onClose}
      title={title}
      searchQuery={search.searchQuery}
      onSearchChange={search.setSearchQuery}
      confirmDisabled={!selected || mergeMutation.isPending}
      onConfirm={() => {
        if (!selected) return
        // Without a source the caller performs the merge itself.
        if (sourceGroupId) mergeMutation.mutate(selected)
        else onSelect?.(selected)
      }}
    >
      <GroupPickerResults
        groups={search.groups}
        isLoading={search.isLoading}
        selectedId={selected?.id ?? null}
        onSelect={setSelected}
        emptyLabel={
          search.debouncedQuery || currentGroupName ? 'No groups found' : 'Type to search groups'
        }
      />
    </GroupPickerShell>
  )
}
