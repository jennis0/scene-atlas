import { useState } from 'react'
import { toast } from 'sonner'
import { imageApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import {
  BULK_CONFIRM_FROM,
  applyBulkChange,
  revertBulkChange,
  tagsToAdd,
  undoBulkChange,
  type BulkChange,
} from '@/lib/bulkEdit'
import type { BulkScope } from '@/hooks/useFileEditing'
import type { BulkImageEditResponse, EditableFileState, TagData } from '@/types'

interface UseBulkImageEditOptions {
  selectedInScope: (scope: BulkScope) => EditableFileState[]
  patchFiles: (paths: Set<string>, transform: (f: EditableFileState) => EditableFileState) => void
  /** After a bulk edit or its undo is saved */
  onSaved: () => void
}

/** A bulk edit waiting for the user to confirm it */
export interface PendingBulkEdit {
  files: EditableFileState[]
  change: BulkChange
}

const images = (n: number) => `${n.toLocaleString()} image${n === 1 ? '' : 's'}`

/**
 * The editor's bulk file actions (tag, grid, type, subgroup) as single
 * `POST /images/bulk-edit` requests, rather than re-saving every group they touch.
 * The change shows at once; a failed request puts the files back. From
 * BULK_CONFIRM_FROM images it asks first, and every edit can be undone from its toast.
 */
export function useBulkImageEdit({
  selectedInScope,
  patchFiles,
  onSaved,
}: UseBulkImageEditOptions) {
  const [pending, setPending] = useState<PendingBulkEdit | null>(null)

  const undo = async (response: BulkImageEditResponse, added: Map<string, TagData[]>) => {
    try {
      await imageApi.bulkRestore(response.previous, response.added_tag_ids)
      const previous = new Map(response.previous.map((p) => [String(p.id), p]))
      patchFiles(new Set(previous.keys()), (f) =>
        undoBulkChange(f, previous.get(f.relative_path)!, added.get(f.relative_path) ?? []),
      )
      onSaved()
      toast.success(`Undone: ${images(response.updated)} put back`)
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Undo failed'))
    }
  }

  const run = async ({ files, change }: PendingBulkEdit) => {
    const before = new Map(files.map((f) => [f.relative_path, f]))
    const added = new Map(files.map((f) => [f.relative_path, tagsToAdd(f, change)]))
    const paths = new Set(before.keys())
    patchFiles(paths, (f) => applyBulkChange(f, change))
    try {
      const response = await imageApi.bulkEdit(
        files.map((f) => Number(f.relative_path)),
        change.changes ?? {},
        change.addTags ?? [],
      )
      onSaved()
      toast.success(`${change.label}: ${images(response.updated)}`, {
        action: { label: 'Undo', onClick: () => void undo(response, added) },
      })
    } catch (err) {
      patchFiles(paths, (f) => revertBulkChange(f, before.get(f.relative_path)!))
      toast.error(getApiErrorMessage(err, `${change.label} failed`))
    }
  }

  /** Run `change` on the selected files of `scope`, asking first if there are many. */
  const request = (scope: BulkScope, change: BulkChange) => {
    const files = selectedInScope(scope)
    if (files.length === 0) return
    if (files.length >= BULK_CONFIRM_FROM) setPending({ files, change })
    else void run({ files, change })
  }

  return {
    request,
    /** The edit awaiting confirmation, if any */
    pending,
    confirm: () => {
      if (pending) void run(pending)
      setPending(null)
    },
    cancel: () => setPending(null),
    describe: (p: PendingBulkEdit) => `${p.change.label} on ${images(p.files.length)}?`,
  }
}
