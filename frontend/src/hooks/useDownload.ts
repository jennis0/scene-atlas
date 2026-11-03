import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { getDownloadUrl } from '@/lib/api'
import { downloadsApi, type DownloadSelection } from '@/lib/api/downloadsApi'
import { postForDownload } from '@/lib/download'
import { getApiErrorMessage } from '@/lib/getErrorMessage'

/**
 * Download groups and images as a zip (design/export-backup-move.md §5). The size is
 * checked first, so a refusal shows as a toast; then the browser downloads the zip itself,
 * streaming it to disk. `busy` covers only the check: the browser shows the download.
 */
export function useDownload() {
  const [busy, setBusy] = useState(false)

  const download = useCallback(async (selection: DownloadSelection, failure: string) => {
    setBusy(true)
    try {
      const check = await downloadsApi.check(selection)
      if (!check.ok) {
        toast.error(check.reason ?? failure)
        return
      }
      postForDownload(getDownloadUrl(), {
        group_ids: (selection.group_ids ?? []).join(','),
        image_ids: (selection.image_ids ?? []).join(','),
      })
    } catch (err) {
      toast.error(getApiErrorMessage(err, failure))
    } finally {
      setBusy(false)
    }
  }, [])

  return { download, busy }
}
