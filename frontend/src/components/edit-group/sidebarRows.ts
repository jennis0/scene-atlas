import type { EditableGroupState, GroupSummary } from '@/types'

/** A loaded group's row, with the group's index in editor state */
export interface LoadedSidebarRow {
  kind: 'group'
  key: string
  group: EditableGroupState
  index: number
}

/** A placeholder: the group is listed from its summary, its files aren't loaded */
interface PendingSidebarRow {
  kind: 'pending'
  key: string
  summary: GroupSummary
}

export type SidebarRow = LoadedSidebarRow | PendingSidebarRow

/**
 * The sidebar's rows: groups in `order` (import review's summary order), loaded or not, so
 * opening a group doesn't move it; then loaded groups outside it (split off, or mass edit,
 * which has no order). `query` keeps rows whose name contains it, ignoring case.
 */
export function sidebarRows(
  groups: EditableGroupState[],
  pending: GroupSummary[],
  order: number[],
  query = '',
): SidebarRow[] {
  const loaded = new Map(groups.map((g, index) => [g.id, index]))
  const placeholders = new Map(pending.map((p) => [p.id, p]))
  const rows: SidebarRow[] = []
  const listed = new Set<string>()
  const pushGroup = (index: number) => {
    const group = groups[index]
    listed.add(group.id)
    rows.push({ kind: 'group', key: `g${group.id}`, group, index })
  }
  for (const id of order) {
    const index = loaded.get(String(id))
    const summary = placeholders.get(id)
    if (index !== undefined) pushGroup(index)
    else if (summary) rows.push({ kind: 'pending', key: `p${id}`, summary })
  }
  groups.forEach((g, index) => listed.has(g.id) || pushGroup(index))
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter((r) =>
    (r.kind === 'group' ? r.group.group_name : r.summary.base_name).toLowerCase().includes(q),
  )
}
