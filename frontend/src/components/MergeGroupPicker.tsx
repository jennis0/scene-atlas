import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ImageIcon, Layers } from 'lucide-react'
import { GroupPickerShell } from '@/components/GroupPickerShell'
import { groupApi, getThumbnailUrlById } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
import type { GroupPickerItem } from '@/types'

interface MergeGroupPickerProps {
  open: boolean
  onClose: () => void
  excludeGroupId?: number | null
  onSelect: (targetGroup: GroupPickerItem) => void
  title?: string
  currentGroupName?: string
}

export function MergeGroupPicker({
  open,
  onClose,
  excludeGroupId,
  onSelect,
  title = 'Merge into Group',
  currentGroupName,
}: MergeGroupPickerProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<GroupPickerItem | null>(null)

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
      confirmDisabled={!selected}
      onConfirm={() => selected && onSelect(selected)}
    >
      {isLoading ? (
        <div className="flex items-center justify-center h-[200px]">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/50" />
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-[200px] text-muted-foreground/60">
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
                {/* Thumbnail */}
                <div className="h-8 w-8 shrink-0 rounded overflow-hidden bg-muted/60 border border-border/30 relative">
                  {/* Fallback icon — always present, covered by image if loaded */}
                  <div className="absolute inset-0 flex items-center justify-center">
                    <ImageIcon className="h-3.5 w-3.5 text-muted-foreground/30" />
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

                {/* Group info */}
                <div className="flex-1 min-w-0">
                  <p
                    className={`text-[13px] font-medium leading-tight truncate ${
                      isSelected ? 'text-primary' : 'text-foreground'
                    }`}
                  >
                    {group.base_name}
                  </p>
                  {group.author && (
                    <p className="text-[11px] text-muted-foreground/60 truncate mt-0.5">
                      {group.author}
                    </p>
                  )}
                </div>

                {/* Image count */}
                <span className="shrink-0 px-1.5 py-px rounded-full bg-primary/15 text-[10px] font-medium text-primary tabular-nums">
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
