import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { groupApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'

/**
 * The search behind a group picker: a debounced query over the groups, leaving out
 * `excludeGroupId` and ranked by likeness to `referenceName` when one is given.
 * Query text resets each time the picker opens.
 */
export function useGroupPickerSearch(
  open: boolean,
  excludeGroupId?: number | null,
  referenceName?: string,
) {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  useEffect(() => {
    if (open) {
      setSearchQuery('')
      setDebouncedQuery('')
    }
  }, [open])

  const { data, isLoading } = useQuery({
    queryKey: QUERY_KEYS.groupSearch(debouncedQuery, excludeGroupId, referenceName),
    queryFn: () =>
      groupApi.search(debouncedQuery, excludeGroupId ?? undefined, 20, referenceName || undefined),
    enabled: open,
  })

  return {
    searchQuery,
    setSearchQuery,
    debouncedQuery,
    groups: data?.groups ?? [],
    isLoading,
  }
}
