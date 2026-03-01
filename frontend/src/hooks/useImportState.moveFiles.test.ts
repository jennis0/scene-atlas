import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFileEditing } from './useFileEditing'
import type { EditableFileState, EditableGroupState } from '@/types'

function makeFile(overrides: Partial<EditableFileState> = {}): EditableFileState {
  return {
    relative_path: 'img.jpg',
    filename: 'img.jpg',
    name: 'img',
    tags: [],
    gridded: null,
    grid_width: null,
    grid_height: null,
    grid_type: null,
    subgroup: null,
    image_type: 'battlemap',
    excluded: false,
    ...overrides,
  }
}

function makeGroup(overrides: Partial<EditableGroupState> = {}): EditableGroupState {
  return {
    id: 'g1',
    author: 'Author',
    group_name: 'Group',
    files: [makeFile()],
    skip: false,
    status: 'pending',
    processed: 0,
    failed: 0,
    total: 1,
    ...overrides,
  }
}

describe('moveFilesToGroup', () => {
  it('moves files from source to target group', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg', name: 'a' })
    const fileB = makeFile({ relative_path: 'b.jpg', name: 'b' })
    const fileC = makeFile({ relative_path: 'c.jpg', name: 'c' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA, fileB], total: 2 }),
        makeGroup({ id: 'g2', files: [fileC], total: 1 }),
      ])
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['a.jpg'])
    })

    expect(result.current.groups[0].files).toHaveLength(1)
    expect(result.current.groups[0].files[0].relative_path).toBe('b.jpg')
    expect(result.current.groups[0].total).toBe(1)
    expect(result.current.groups[1].files).toHaveLength(2)
    expect(result.current.groups[1].files[1].relative_path).toBe('a.jpg')
    expect(result.current.groups[1].total).toBe(2)
  })

  it('removes empty source group after move', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })
    const fileB = makeFile({ relative_path: 'b.jpg' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA], total: 1 }),
        makeGroup({ id: 'g2', files: [fileB], total: 1 }),
      ])
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['a.jpg'])
    })

    expect(result.current.groups).toHaveLength(1)
    expect(result.current.groups[0].id).toBe('g2')
  })

  it('clears selection for source group after move', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })
    const fileB = makeFile({ relative_path: 'b.jpg' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA, fileB], total: 2 }),
        makeGroup({ id: 'g2', files: [], total: 0 }),
      ])
    })

    act(() => {
      result.current.toggleFileSelection('g1', 'a.jpg')
      result.current.toggleFileSelection('g1', 'b.jpg')
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['a.jpg'])
    })

    expect(result.current.selections['g1']?.size ?? 0).toBe(0)
  })

  it('is a no-op when source group does not exist', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })

    act(() => {
      result.current.setGroups([makeGroup({ id: 'g1', files: [fileA], total: 1 })])
    })

    act(() => {
      result.current.moveFilesToGroup('nonexistent', 'g1', ['a.jpg'])
    })

    expect(result.current.groups).toHaveLength(1)
    expect(result.current.groups[0].files).toHaveLength(1)
  })

  it('is a no-op when none of the specified paths exist in source', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })
    const fileB = makeFile({ relative_path: 'b.jpg' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA], total: 1 }),
        makeGroup({ id: 'g2', files: [fileB], total: 1 }),
      ])
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['nonexistent.jpg'])
    })

    expect(result.current.groups[0].files).toHaveLength(1)
    expect(result.current.groups[1].files).toHaveLength(1)
  })

  it('is a no-op when moving to the same group', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })
    const fileB = makeFile({ relative_path: 'b.jpg' })

    act(() => {
      result.current.setGroups([makeGroup({ id: 'g1', files: [fileA, fileB], total: 2 })])
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g1', ['a.jpg'])
    })

    // Files should not be duplicated — source and target are the same
    expect(result.current.groups[0].files).toHaveLength(2)
  })

  it('updates totals correctly when moving multiple files', () => {
    const { result } = renderHook(() => useFileEditing())
    const fileA = makeFile({ relative_path: 'a.jpg' })
    const fileB = makeFile({ relative_path: 'b.jpg' })
    const fileC = makeFile({ relative_path: 'c.jpg' })
    const fileD = makeFile({ relative_path: 'd.jpg' })

    act(() => {
      result.current.setGroups([
        makeGroup({ id: 'g1', files: [fileA, fileB, fileC], total: 3 }),
        makeGroup({ id: 'g2', files: [fileD], total: 1 }),
      ])
    })

    act(() => {
      result.current.moveFilesToGroup('g1', 'g2', ['a.jpg', 'c.jpg'])
    })

    expect(result.current.groups[0].total).toBe(1)
    expect(result.current.groups[0].files).toHaveLength(1)
    expect(result.current.groups[0].files[0].relative_path).toBe('b.jpg')
    expect(result.current.groups[1].total).toBe(3)
    expect(result.current.groups[1].files).toHaveLength(3)
  })
})
