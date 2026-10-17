import { useCallback, useRef } from 'react'
import { groupApi } from '@/lib/api'
import { withServerFields } from '@/lib/bulkEdit'
import { imageToEditable } from '@/hooks/useEditGroupLoad'
import type { EditableFileState, EditableGroupState } from '@/types'

type PatchFiles = (
  paths: Set<string>,
  transform: (f: EditableFileState) => EditableFileState,
) => void

/**
 * Re-read the editor's loaded files from the server after a change made there (an undo,
 * or a bulk edit by scope), keeping each file's editor-only state (selection scope,
 * exclusion). Only groups holding one of `paths` are fetched, or every loaded group.
 */
export function useRefreshLoaded(groups: EditableGroupState[], patchFiles: PatchFiles) {
  // Read at call time: the refresh runs after awaits, when these may have changed
  const latest = useRef({ groups, patchFiles })
  latest.current = { groups, patchFiles }

  return useCallback(async (paths?: Set<string>) => {
    const ids = latest.current.groups
      .filter((g) => !paths || g.files.some((f) => paths.has(f.relative_path)))
      .map((g) => Number(g.id))
      .filter((id) => !Number.isNaN(id))
    if (ids.length === 0) return
    const details = await groupApi.details(ids)
    const fresh = new Map(
      details.flatMap((d) => d.images.map((img) => [String(img.id), imageToEditable(img)])),
    )
    latest.current.patchFiles(new Set(fresh.keys()), (f) =>
      withServerFields(f, fresh.get(f.relative_path)!),
    )
  }, [])
}
