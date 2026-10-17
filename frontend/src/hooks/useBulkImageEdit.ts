import { useState } from 'react'
import { toast } from 'sonner'
import { imageApi } from '@/lib/api'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import {
  BULK_CONFIRM_FROM,
  applyBulkChange,
  revertBulkChange,
  type BulkChange,
} from '@/lib/bulkEdit'
import type { BulkScope } from '@/hooks/useFileEditing'
import type { EditableFileState, ImageScope } from '@/types'

interface UseBulkImageEditOptions {
  selectedInScope: (scope: BulkScope) => EditableFileState[]
  patchFiles: (paths: Set<string>, transform: (f: EditableFileState) => EditableFileState) => void
  /** Re-read loaded files from the server (all of them, or those in `paths`) after a
   *  change made there: an undo, or an edit by scope */
  refreshLoaded: (paths?: Set<string>) => Promise<void>
  /** After a bulk edit or its undo is saved */
  onSaved: () => void
}

/** What a bulk edit applies to: selected files, or a scope resolved on the server */
type BulkTarget =
  | { kind: 'files'; files: EditableFileState[] }
  | { kind: 'scope'; scope: ImageScope; count: number }

/** A bulk edit waiting for the user to confirm it */
export interface PendingBulkEdit {
  target: BulkTarget
  change: BulkChange
}

const images = (n: number) => `${n.toLocaleString()} image${n === 1 ? '' : 's'}`
const countOf = (t: BulkTarget) => (t.kind === 'files' ? t.files.length : t.count)

/**
 * The editor's bulk edits (tag, grid, type, subgroup) as single `POST /images/bulk-edit`
 * requests. Selected files change at once and go back if the request fails; a scope (the
 * bulk panel's "everything in this import", maybe filtered) is resolved on the server and
 * the loaded files re-read after. From BULK_CONFIRM_FROM images it asks first, and every
 * edit can be undone from its toast (the server keeps the undo).
 */
export function useBulkImageEdit({
  selectedInScope,
  patchFiles,
  refreshLoaded,
  onSaved,
}: UseBulkImageEditOptions) {
  const [pending, setPending] = useState<PendingBulkEdit | null>(null)

  const undo = async (undoId: string, updated: number, paths?: Set<string>) => {
    try {
      await imageApi.bulkRestore(undoId)
      await refreshLoaded(paths)
      onSaved()
      toast.success(`Undone: ${images(updated)} put back`)
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Undo failed'))
    }
  }

  const send = async ({ target, change }: PendingBulkEdit) => {
    const request =
      target.kind === 'files'
        ? { image_ids: target.files.map((f) => Number(f.relative_path)) }
        : { scope: target.scope }
    return imageApi.bulkEdit(request, change.changes ?? {}, change.addTags ?? [])
  }

  const run = async (edit: PendingBulkEdit) => {
    const { target, change } = edit
    const before = new Map(
      target.kind === 'files' ? target.files.map((f) => [f.relative_path, f]) : [],
    )
    const paths = target.kind === 'files' ? new Set(before.keys()) : undefined
    if (paths) patchFiles(paths, (f) => applyBulkChange(f, change))
    try {
      const response = await send(edit)
      if (!paths) await refreshLoaded()
      onSaved()
      toast.success(`${change.label}: ${images(response.updated)}`, {
        action: {
          label: 'Undo',
          onClick: () => void undo(response.undo_id, response.updated, paths),
        },
      })
    } catch (err) {
      if (paths) patchFiles(paths, (f) => revertBulkChange(f, before.get(f.relative_path)!))
      toast.error(getApiErrorMessage(err, `${change.label} failed`))
    }
  }

  const start = (edit: PendingBulkEdit) => {
    const count = countOf(edit.target)
    if (count === 0) return
    if (count >= BULK_CONFIRM_FROM) setPending(edit)
    else void run(edit)
  }

  return {
    /** Edit the selected files of `scope` (a BulkScope: one group, several, or all) */
    request: (scope: BulkScope, change: BulkChange) =>
      start({ target: { kind: 'files', files: selectedInScope(scope) }, change }),
    /** Edit every image of a server-side scope; `count` is how many it holds */
    requestScope: (scope: ImageScope, count: number, change: BulkChange) =>
      start({ target: { kind: 'scope', scope, count }, change }),
    /** The edit awaiting confirmation, if any */
    pending,
    confirm: () => {
      if (pending) void run(pending)
      setPending(null)
    },
    cancel: () => setPending(null),
    describe: (p: PendingBulkEdit) => `${p.change.label} on ${images(countOf(p.target))}?`,
  }
}
