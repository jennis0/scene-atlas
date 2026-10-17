import { describe, expect, it } from 'vitest'
import type { EditableGroupState, GroupSummary } from '@/types'
import { sidebarRows } from './sidebarRows'

const group = (id: number, name = `G${id}`) =>
  ({ id: String(id), group_name: name, author: '', files: [] }) as EditableGroupState
const summary = (id: number, name = `G${id}`) =>
  ({
    id,
    base_name: name,
    author: null,
    primary_image_id: null,
    image_count: 1,
    image_ids: [],
  }) as GroupSummary
const keys = (rows: ReturnType<typeof sidebarRows>) => rows.map((r) => r.key)

describe('sidebarRows', () => {
  it('keeps summary order whether or not a group is loaded', () => {
    // Group 3 was opened first, so it's first in editor state
    const rows = sidebarRows([group(3), group(1)], [summary(2), summary(4)], [1, 2, 3, 4])
    expect(keys(rows)).toEqual(['g1', 'p2', 'g3', 'p4'])
    expect(rows.find((r) => r.key === 'g3')).toMatchObject({ index: 0 })
  })

  it('lists loaded groups outside the order after it, and drops ones that are gone', () => {
    const rows = sidebarRows([group(1), group(9)], [], [1, 2])
    expect(keys(rows)).toEqual(['g1', 'g9'])
  })

  it('filters by name, ignoring case', () => {
    const rows = sidebarRows([group(1, 'Forest Path')], [summary(2, 'Cave')], [1, 2], ' forest ')
    expect(keys(rows)).toEqual(['g1'])
  })
})
