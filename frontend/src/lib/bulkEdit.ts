import type { BulkImageChanges, EditableFileState, TagData } from '@/types'

/** From this many images, a bulk edit asks before it runs */
export const BULK_CONFIRM_FROM = 500

/** One bulk action: fields to set and/or tags to add, and how to describe it */
export interface BulkChange {
  changes?: BulkImageChanges
  addTags?: TagData[]
  /** e.g. 'Add tag "night"', shown in the confirmation and the toast */
  label: string
}

const hasTag = (f: EditableFileState, t: TagData) =>
  f.tags.some((x) => x.category === t.category && x.value === t.value)

const tagsToAdd = (file: EditableFileState, change: BulkChange): TagData[] =>
  (change.addTags ?? []).filter((t) => !hasTag(file, t))

/** A file as the server leaves it after `change` (POST /images/bulk-edit). */
export function applyBulkChange(file: EditableFileState, change: BulkChange): EditableFileState {
  const changes = change.changes ?? {}
  // Turning the grid off clears the grid fields the change doesn't set, as on the server
  const cleared =
    changes.gridded === false ? { grid_type: null, grid_width: null, grid_height: null } : {}
  const added = tagsToAdd(file, change)
  return {
    ...file,
    ...cleared,
    ...changes,
    image_type: changes.image_type ?? file.image_type,
    tags: added.length > 0 ? [...file.tags, ...added] : file.tags,
  }
}

/** Fields a bulk edit can change, copied from `before` (to put a file back after a failed request). */
export function revertBulkChange(
  file: EditableFileState,
  before: EditableFileState,
): EditableFileState {
  const { image_type, subgroup, gridded, grid_type, grid_width, grid_height, tags } = before
  return { ...file, image_type, subgroup, gridded, grid_type, grid_width, grid_height, tags }
}

/** A file with the bulk-editable fields of `fresh` (the same file as just read from the server). */
export function withServerFields(
  file: EditableFileState,
  fresh: EditableFileState,
): EditableFileState {
  return revertBulkChange(file, fresh)
}

/** Describe a grid change for the confirmation and toast. */
export function gridLabel(gridded: boolean | null, gridType: string | null): string {
  if (gridded === null) return 'Mark grid as unknown'
  if (!gridded) return 'Mark as ungridded'
  return gridType ? `Set grid to ${gridType}` : 'Mark as gridded'
}
