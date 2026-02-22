import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Loader2, ImageIcon, Layers } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { groupApi, getThumbnailUrlById } from '@/lib/api'
import type { GroupSearchItem } from '@/types'

interface MergeGroupPickerProps {
  open: boolean
  onClose: () => void
  excludeGroupId?: number | null
  onSelect: (targetGroup: GroupSearchItem) => void
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
  const [selected, setSelected] = useState<GroupSearchItem | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

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
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  const { data, isLoading } = useQuery({
    queryKey: ['groupSearch', debouncedQuery, excludeGroupId, currentGroupName],
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
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md p-0 overflow-hidden gap-0" onClose={onClose}>
        {/* Header */}
        <DialogHeader className="px-5 pt-5 pb-0">
          <DialogTitle className="text-[15px] tracking-wide">{title}</DialogTitle>
        </DialogHeader>

        {/* Search bar */}
        <div className="px-5 pt-3 pb-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/60" />
            <input
              ref={inputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search groups..."
              className="w-full h-8 pl-8 pr-3 text-sm bg-muted/40 border border-border/50 rounded-md text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-colors"
            />
          </div>
        </div>

        {/* Results list */}
        <div className="min-h-[200px] max-h-[320px] overflow-y-auto px-2 pb-2 scrollbar-thin">
          {isLoading ? (
            <div className="flex items-center justify-center h-[200px]">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/50" />
            </div>
          ) : groups.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-[200px] text-muted-foreground/50">
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
                    <div className="h-8 w-8 shrink-0 rounded overflow-hidden bg-muted/60 border border-border/30">
                      {group.primary_image_id ? (
                        <img
                          src={getThumbnailUrlById(group.primary_image_id)}
                          alt=""
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="h-full w-full flex items-center justify-center">
                          <ImageIcon className="h-3.5 w-3.5 text-muted-foreground/30" />
                        </div>
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
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground/50 bg-muted/40 px-1.5 py-0.5 rounded">
                      {group.image_count}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-border/30 bg-muted/10">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md border border-border/50 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => selected && onSelect(selected)}
            disabled={!selected}
            className="px-4 py-1.5 text-sm rounded-md font-medium bg-primary/90 text-primary-foreground hover:bg-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Merge
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
