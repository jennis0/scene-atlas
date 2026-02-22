import { describe, it, expect } from 'vitest'
import { applyFileFilter, EMPTY_FILTER } from './fileFilter'
import type { FileFilter } from './fileFilter'
import type { EditableFileState } from '@/types'

function makeFile(overrides: Partial<EditableFileState>): EditableFileState {
  return {
    relative_path: 'group/file.jpg',
    filename: 'file.jpg',
    name: 'File',
    tags: [],
    gridded: null,
    grid_width: null,
    grid_height: null,
    grid_type: null,
    subgroup: null,
    excluded: false,
    media_type: 'image',
    image_type: 'battlemap',
    ...overrides,
  }
}

describe('applyFileFilter', () => {
  describe('EMPTY_FILTER', () => {
    it('returns all files when filter is empty', () => {
      const files = [makeFile({ filename: 'a.jpg' }), makeFile({ filename: 'b.jpg' })]
      expect(applyFileFilter(files, EMPTY_FILTER)).toHaveLength(2)
    })
  })

  describe('text filter', () => {
    it('filters by filename (case-insensitive)', () => {
      const files = [makeFile({ filename: 'Forest.jpg' }), makeFile({ filename: 'dungeon.jpg' })]
      const filter: FileFilter = { ...EMPTY_FILTER, text: 'forest' }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
      expect(applyFileFilter(files, filter)[0].filename).toBe('Forest.jpg')
    })

    it('filters by name field (case-insensitive)', () => {
      const files = [
        makeFile({ filename: 'a.jpg', name: 'Forest Clearing' }),
        makeFile({ filename: 'b.jpg', name: 'Dark Dungeon' }),
      ]
      const filter: FileFilter = { ...EMPTY_FILTER, text: 'dungeon' }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
    })

    it('returns empty when no match', () => {
      const files = [makeFile({ filename: 'forest.jpg' })]
      const filter: FileFilter = { ...EMPTY_FILTER, text: 'dungeon' }
      expect(applyFileFilter(files, filter)).toHaveLength(0)
    })
  })

  describe('imageType filter', () => {
    it('passes all through when imageType is "all"', () => {
      const files = [
        makeFile({ image_type: 'battlemap' }),
        makeFile({ image_type: 'scene' }),
        makeFile({ image_type: undefined }), // defaults to battlemap
      ]
      expect(applyFileFilter(files, EMPTY_FILTER)).toHaveLength(3)
    })

    it('filters to battlemap only', () => {
      const files = [makeFile({ image_type: 'battlemap' }), makeFile({ image_type: 'scene' })]
      const filter: FileFilter = { ...EMPTY_FILTER, imageType: 'battlemap' }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
      expect(applyFileFilter(files, filter)[0].image_type).toBe('battlemap')
    })

    it('filters to scene only', () => {
      const files = [makeFile({ image_type: 'battlemap' }), makeFile({ image_type: 'scene' })]
      const filter: FileFilter = { ...EMPTY_FILTER, imageType: 'scene' }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
    })

    it('treats undefined image_type as battlemap', () => {
      const files = [makeFile({ image_type: undefined })]
      const filter: FileFilter = { ...EMPTY_FILTER, imageType: 'battlemap' }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
    })
  })

  describe('subgroup active filter', () => {
    it('includes only matching subgroup', () => {
      const files = [
        makeFile({ subgroup: 'snowy' }),
        makeFile({ subgroup: 'summer' }),
        makeFile({ subgroup: null }),
      ]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'subgroup', value: 'snowy', label: 'snowy', exclude: false }],
      }
      const result = applyFileFilter(files, filter)
      expect(result).toHaveLength(1)
      expect(result[0].subgroup).toBe('snowy')
    })

    it('excludes matching subgroup when exclude=true', () => {
      const files = [makeFile({ subgroup: 'snowy' }), makeFile({ subgroup: 'summer' })]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'subgroup', value: 'snowy', label: 'snowy', exclude: true }],
      }
      const result = applyFileFilter(files, filter)
      expect(result).toHaveLength(1)
      expect(result[0].subgroup).toBe('summer')
    })
  })

  describe('tag active filter', () => {
    it('includes only files with matching tag', () => {
      const files = [
        makeFile({
          tags: [{ category: 'environment', value: 'forest', confidence: 1, source: 'manual' }],
        }),
        makeFile({ tags: [] }),
      ]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'tag', value: 'environment:forest', label: 'forest', exclude: false }],
      }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
    })

    it('excludes files with matching tag when exclude=true', () => {
      const files = [
        makeFile({
          tags: [{ category: 'environment', value: 'forest', confidence: 1, source: 'manual' }],
        }),
        makeFile({ tags: [] }),
      ]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'tag', value: 'environment:forest', label: 'forest', exclude: true }],
      }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
      expect(applyFileFilter(files, filter)[0].tags).toHaveLength(0)
    })
  })

  describe('gridded active filter', () => {
    it('filters to gridded files', () => {
      const files = [
        makeFile({ gridded: true }),
        makeFile({ gridded: false }),
        makeFile({ gridded: null }),
      ]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'gridded', value: 'gridded', label: 'Gridded', exclude: false }],
      }
      const result = applyFileFilter(files, filter)
      expect(result).toHaveLength(1)
      expect(result[0].gridded).toBe(true)
    })

    it('filters to gridless files', () => {
      const files = [
        makeFile({ gridded: true }),
        makeFile({ gridded: false }),
        makeFile({ gridded: null }),
      ]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'gridded', value: 'gridless', label: 'Gridless', exclude: false }],
      }
      const result = applyFileFilter(files, filter)
      expect(result).toHaveLength(1)
      expect(result[0].gridded).toBe(false)
    })

    it('filters to unknown-grid files (value="unknown")', () => {
      const files = [
        makeFile({ gridded: true }),
        makeFile({ gridded: false }),
        makeFile({ gridded: null }),
      ]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'gridded', value: 'unknown', label: 'Unknown', exclude: false }],
      }
      const result = applyFileFilter(files, filter)
      expect(result).toHaveLength(1)
      expect(result[0].gridded).toBeNull()
    })
  })

  describe('media_type active filter', () => {
    it('filters to images only', () => {
      const files = [makeFile({ media_type: 'image' }), makeFile({ media_type: 'video' })]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'media_type', value: 'image', label: 'Image', exclude: false }],
      }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
    })

    it('filters to videos only', () => {
      const files = [makeFile({ media_type: 'image' }), makeFile({ media_type: 'video' })]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'media_type', value: 'video', label: 'Video', exclude: false }],
      }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
    })

    it('defaults to "image" when media_type is undefined', () => {
      const files = [makeFile({ media_type: undefined })]
      const filter: FileFilter = {
        ...EMPTY_FILTER,
        active: [{ type: 'media_type', value: 'image', label: 'Image', exclude: false }],
      }
      expect(applyFileFilter(files, filter)).toHaveLength(1)
    })
  })

  describe('combined filters', () => {
    it('applies text and active filters together (AND logic)', () => {
      const files = [
        makeFile({ filename: 'forest.jpg', subgroup: 'snowy' }),
        makeFile({ filename: 'forest.jpg', subgroup: 'summer' }),
        makeFile({ filename: 'dungeon.jpg', subgroup: 'snowy' }),
      ]
      const filter: FileFilter = {
        text: 'forest',
        imageType: 'all',
        active: [{ type: 'subgroup', value: 'snowy', label: 'snowy', exclude: false }],
      }
      const result = applyFileFilter(files, filter)
      expect(result).toHaveLength(1)
      expect(result[0].filename).toBe('forest.jpg')
      expect(result[0].subgroup).toBe('snowy')
    })
  })
})
