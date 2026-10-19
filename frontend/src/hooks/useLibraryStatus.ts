import { useQuery } from '@tanstack/react-query'
import { libraryApi } from '@/lib/api/libraryApi'
import { QUERY_KEYS } from '@/lib/queryKeys'

/** The library and its linked folder (GET /library/status): often while a scan runs, so the
 * folder's state and counts stay current, and once a minute otherwise. */
export function useLibraryStatus(enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.libraryStatus,
    queryFn: libraryApi.status,
    enabled,
    staleTime: 5_000,
    refetchInterval: (query) => (query.state.data?.linked?.scanning ? 5_000 : 60_000),
  })
}
