// Shared DnD types

export interface DragData {
  type: 'card' | 'group'
  id: string // relative_path for cards, group id for groups
  groupId: string // source group id
}

export interface DropData {
  type: 'group' | 'subgroup'
  groupId?: string
  subgroup?: string | null
}

export interface ActiveDragState {
  type: 'card' | 'group'
  id: string
  groupId: string
  selectedCount: number
  previewUrl?: string
  label?: string
  /** When dragging a group that is part of a multi-selection, contains all selected group IDs */
  selectedGroupIds?: Set<string>
}
