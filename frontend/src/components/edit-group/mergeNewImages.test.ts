import { describe, expect, it } from 'vitest'
import { imageToEditable } from '@/hooks/useEditGroupLoad'
import type { EditableGroupState, GroupDetail, Image } from '@/types'
import { withNewImages } from './mergeNewImages'

const image = (id: number) =>
  ({
    id,
    filename: `${id}.png`,
    name: `Image ${id}`,
    tags: [],
    image_type: 'battlemap',
    media_type: 'image',
  }) as unknown as Image

const loaded = (id: string, imageIds: number[]): EditableGroupState => ({
  id,
  author: 'A',
  group_name: `Group ${id}`,
  files: imageIds.map((i) => imageToEditable(image(i))),
})

const detail = (id: number, imageIds: number[]) =>
  ({
    id,
    base_name: `Group ${id}`,
    author: 'A',
    images: imageIds.map(image),
  }) as unknown as GroupDetail

describe('withNewImages', () => {
  it('appends images the server has, keeping loaded files and their edits', () => {
    const group = loaded('7', [1, 2])
    group.files[0] = { ...group.files[0], name: 'Renamed', excluded: true }
    const [merged, other] = withNewImages([group, loaded('8', [5])], [detail(7, [1, 2, 3])])
    expect(merged.files.map((f) => f.relative_path)).toEqual(['1', '2', '3'])
    expect(merged.files[0]).toMatchObject({ name: 'Renamed', excluded: true })
    expect(other.files.map((f) => f.relative_path)).toEqual(['5'])
  })

  it('returns the same group object when nothing is new', () => {
    const group = loaded('7', [1])
    expect(withNewImages([group], [detail(7, [1])])[0]).toBe(group)
  })
})
