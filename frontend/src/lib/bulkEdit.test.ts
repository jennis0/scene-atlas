import { describe, expect, it } from 'vitest'
import type { EditableFileState, ImageRestoreState, TagData } from '@/types'
import { applyBulkChange, gridLabel, revertBulkChange, tagsToAdd, undoBulkChange } from './bulkEdit'

const file = (overrides: Partial<EditableFileState> = {}): EditableFileState => ({
  relative_path: '1',
  filename: 'a.jpg',
  name: 'a',
  tags: [],
  gridded: true,
  grid_width: 20,
  grid_height: 15,
  grid_type: 'square',
  subgroup: null,
  image_type: 'battlemap',
  excluded: false,
  ...overrides,
})
const night: TagData = { category: 'lighting', value: 'night', confidence: 1, source: 'manual' }

describe('applyBulkChange', () => {
  it('adds a tag once', () => {
    const once = applyBulkChange(file(), { addTags: [night], label: '' })
    expect(once.tags).toEqual([night])
    expect(applyBulkChange(once, { addTags: [night], label: '' }).tags).toEqual([night])
    expect(tagsToAdd(once, { addTags: [night], label: '' })).toEqual([])
  })

  it('sets only the fields in the change, null included', () => {
    const changed = applyBulkChange(file({ subgroup: 'Winter' }), {
      changes: { image_type: 'scene', subgroup: null },
      label: '',
    })
    expect(changed).toMatchObject({ image_type: 'scene', subgroup: null, grid_type: 'square' })
  })

  it('turning the grid off clears its fields, as the server does', () => {
    const off = applyBulkChange(file(), { changes: { gridded: false, grid_type: null }, label: '' })
    expect(off).toMatchObject({
      gridded: false,
      grid_type: null,
      grid_width: null,
      grid_height: null,
    })
  })
})

describe('revert and undo', () => {
  it('revert copies back the bulk-editable fields', () => {
    const before = file({ tags: [night] })
    const after = applyBulkChange(before, {
      changes: { gridded: false, image_type: 'scene' },
      label: '',
    })
    expect(revertBulkChange({ ...after, name: 'renamed' }, before)).toEqual({
      ...before,
      name: 'renamed',
    })
  })

  it('undo restores the server state and drops only the added tags', () => {
    const previous: ImageRestoreState = {
      id: 1,
      image_type: 'battlemap',
      subgroup: null,
      gridded: true,
      grid_width: 20,
      grid_height: 15,
      grid_type: 'square',
      grid_source: 'detector',
      grid_confidence: 0.9,
    }
    const kept: TagData = { ...night, value: 'day' }
    const edited = file({
      gridded: false,
      grid_type: null,
      image_type: 'scene',
      tags: [kept, night],
    })
    expect(undoBulkChange(edited, previous, [night])).toEqual(file({ tags: [kept] }))
  })
})

describe('gridLabel', () => {
  it('describes each grid choice', () => {
    expect(gridLabel(true, 'hex')).toBe('Set grid to hex')
    expect(gridLabel(false, null)).toBe('Mark as ungridded')
    expect(gridLabel(null, null)).toBe('Mark grid as unknown')
  })
})
