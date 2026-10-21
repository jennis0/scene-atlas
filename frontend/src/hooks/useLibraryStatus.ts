import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { libraryApi } from '@/lib/api/libraryApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { getImportManager } from '@/lib/import/ImportManager'
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

/** "Check for changes" in the linked folder, on request */
export function useCheckLinkedFolder(failure: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => libraryApi.scan('manual'),
    // A scan that finds files creates an import job: pick it up now, not at the idle poll
    onSuccess: () => void getImportManager().refresh(),
    onError: (err) => toast.error(getApiErrorMessage(err, failure)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: QUERY_KEYS.libraryStatus }),
  })
}
