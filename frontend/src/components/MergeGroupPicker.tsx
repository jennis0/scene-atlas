import { useState, useEffect } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { Loader2, ImageIcon, Layers } from 'lucide-react'
import { GroupPickerShell } from '@/components/GroupPickerShell'
import { groupApi, getThumbnailUrlById } from '@/lib/api'
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
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
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

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setSearchQuery('')
      setDebouncedQuery('')
      setSelected(null)
    }
  }, [open])

  const { data, isLoading } = useQuery({
    queryKey: QUERY_KEYS.groupSearch(debouncedQuery, excludeGroupId, currentGroupName),
    queryFn: () =>
      groupApi.search(
        debouncedQuery,
        excludeGroupId ?? undefined,
        20,
        currentGroupName || undefined,
      ),
    enabled: open,
  })

  const groups = data?.groups ?? []

  return (
    <GroupPickerShell
      open={open}
      onClose={onClose}
      title={title}
      searchQuery={searchQuery}
      onSearchChange={setSearchQuery}
      confirmDisabled={!selected || mergeMutation.isPending}
      onConfirm={() => {
        if (!selected) return
        // Without a source the caller performs the merge itself.
        if (sourceGroupId) mergeMutation.mutate(selected)
        else onSelect?.(selected)
      }}
    >
      {isLoading ? (
        <div className="flex items-center justify-center h-[11.76rem]">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-[11.76rem] text-muted-foreground">
          <Layers className="h-8 w-8 mb-2 opacity-40" />
          <p className="text-sm">
            {debouncedQuery || currentGroupName ? 'No groups found' : 'Type to search groups'}
          </p>
        </div>
      ) : (
        <div className="space-y-px">
          {groups.map((group) => {
            const isSelected = selected?.id === group.id
            return (
              <button
                key={group.id}
                onClick={() => setSelected(group)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-all duration-100 ${
                  isSelected ? 'bg-primary/15 ring-1 ring-primary/40' : 'hover:bg-muted/50'
                }`}
              >
                <div className="h-8 w-8 shrink-0 rounded overflow-hidden bg-muted/60 border border-border/30 relative">
                  {/* Fallback icon — always present, covered by image if loaded */}
                  <div className="absolute inset-0 flex items-center justify-center">
                    <ImageIcon className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                  {group.primary_image_id && (
                    <img
                      src={getThumbnailUrlById(group.primary_image_id)}
                      alt=""
                      loading="eager"
                      onError={(e) => {
                        e.currentTarget.style.display = 'none'
                      }}
                      className="absolute inset-0 h-full w-full object-cover"
                    />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <p
                    className={`text-xs font-medium leading-tight truncate ${
                      isSelected ? 'text-primary' : 'text-foreground'
                    }`}
                  >
                    {group.base_name}
                  </p>
                  {group.author && (
                    <p className="text-2xs text-muted-foreground truncate mt-0.5">{group.author}</p>
                  )}
                </div>

                <span className="shrink-0 px-1.5 py-px rounded-full bg-primary/15 text-3xs font-medium text-primary tabular-nums">
                  {group.image_count}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </GroupPickerShell>
  )
}
