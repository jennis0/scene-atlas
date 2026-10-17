import type { BulkImageChanges, EditableFileState, ImageRestoreState, TagData } from '@/types'

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

/** The tags of `change` that `file` doesn't have yet. */
export function tagsToAdd(file: EditableFileState, change: BulkChange): TagData[] {
  return (change.addTags ?? []).filter((t) => !hasTag(file, t))
}

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

/** Fields a bulk edit can change, copied back from `before` (when the request fails). */
export function revertBulkChange(
  file: EditableFileState,
  before: EditableFileState,
): EditableFileState {
  const { image_type, subgroup, gridded, grid_type, grid_width, grid_height, tags } = before
  return { ...file, image_type, subgroup, gridded, grid_type, grid_width, grid_height, tags }
}

/** A file after an undo: the server's previous state, without the tags the edit added. */
export function undoBulkChange(
  file: EditableFileState,
  previous: ImageRestoreState,
  addedTags: TagData[],
): EditableFileState {
  return {
    ...file,
    image_type: previous.image_type === 'scene' ? 'scene' : 'battlemap',
    subgroup: previous.subgroup,
    gridded: previous.gridded,
    grid_type: previous.grid_type,
    grid_width: previous.grid_width,
    grid_height: previous.grid_height,
    tags: file.tags.filter(
      (t) => !addedTags.some((a) => a.category === t.category && a.value === t.value),
    ),
  }
}

/** Describe a grid change for the confirmation and toast. */
export function gridLabel(gridded: boolean | null, gridType: string | null): string {
  if (gridded === null) return 'Mark grid as unknown'
  if (!gridded) return 'Mark as ungridded'
  return gridType ? `Set grid to ${gridType}` : 'Mark as gridded'
}
