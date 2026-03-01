import { describe, it, expect } from 'vitest'
import { splitIntoBatches, isClientError } from './useImportUpload'
import { MAX_BATCH_FILES, MAX_BATCH_BYTES } from '@/lib/constants'

function mockFile(name: string, sizeBytes: number): File {
  return { name, size: sizeBytes } as File
}

// ── splitIntoBatches ──────────────────────────────────────────────────────────

describe('splitIntoBatches', () => {
  it('returns an empty array for empty input', () => {
    const result = splitIntoBatches([], [])
    expect(result).toEqual([])
  })

  it('returns one batch for a single small file', () => {
    const files = [mockFile('a.png', 1024)]
    const paths = ['a.png']
    const result = splitIntoBatches(files, paths)
    expect(result).toHaveLength(1)
    expect(result[0].files).toHaveLength(1)
    expect(result[0].relativePaths).toEqual(['a.png'])
  })

  it('returns one batch for two files both under limits', () => {
    const files = [mockFile('a.png', 1024), mockFile('b.png', 2048)]
    const paths = ['a.png', 'b.png']
    const result = splitIntoBatches(files, paths)
    expect(result).toHaveLength(1)
    expect(result[0].files).toHaveLength(2)
    expect(result[0].relativePaths).toEqual(['a.png', 'b.png'])
  })

  it(`splits 21 files (exceeding MAX_BATCH_FILES=${MAX_BATCH_FILES}) into [20, 1]`, () => {
    const files = Array.from({ length: 21 }, (_, i) => mockFile(`file${i}.png`, 100))
    const paths = files.map((f) => f.name)
    const result = splitIntoBatches(files, paths)
    expect(result).toHaveLength(2)
    expect(result[0].files).toHaveLength(20)
    expect(result[1].files).toHaveLength(1)
  })

  it('splits two 60MB files (exceeding MAX_BATCH_BYTES) into two batches of [1, 1]', () => {
    const sixtyMB = 60 * 1024 * 1024
    const files = [mockFile('big1.png', sixtyMB), mockFile('big2.png', sixtyMB)]
    const paths = ['big1.png', 'big2.png']
    const result = splitIntoBatches(files, paths)
    expect(result).toHaveLength(2)
    expect(result[0].files).toHaveLength(1)
    expect(result[1].files).toHaveLength(1)
  })

  it('places a single file larger than MAX_BATCH_BYTES alone in one batch (no infinite loop)', () => {
    const oversize = MAX_BATCH_BYTES + 1
    const files = [mockFile('huge.png', oversize)]
    const paths = ['huge.png']
    const result = splitIntoBatches(files, paths)
    expect(result).toHaveLength(1)
    expect(result[0].files).toHaveLength(1)
    expect(result[0].files[0].name).toBe('huge.png')
  })

  it('splits at the byte boundary: exactly MAX_BATCH_BYTES + 1 extra byte triggers a second batch', () => {
    // First file fills the entire budget, second file cannot fit — expect 2 batches
    const files = [mockFile('full.png', MAX_BATCH_BYTES), mockFile('extra.png', 1)]
    const paths = ['full.png', 'extra.png']
    const result = splitIntoBatches(files, paths)
    expect(result).toHaveLength(2)
    expect(result[0].files).toHaveLength(1)
    expect(result[1].files).toHaveLength(1)
  })

  it('keeps relativePaths arrays aligned with their files in each batch', () => {
    // 21 files so we get two batches; verify path alignment
    const files = Array.from({ length: 21 }, (_, i) => mockFile(`img${i}.png`, 100))
    const paths = files.map((_, i) => `subdir/img${i}.png`)
    const result = splitIntoBatches(files, paths)
    expect(result).toHaveLength(2)
    // First batch: 20 files
    for (let i = 0; i < 20; i++) {
      expect(result[0].files[i].name).toBe(`img${i}.png`)
      expect(result[0].relativePaths[i]).toBe(`subdir/img${i}.png`)
    }
    // Second batch: 1 file
    expect(result[1].files[0].name).toBe('img20.png')
    expect(result[1].relativePaths[0]).toBe('subdir/img20.png')
  })
})

// ── isClientError ─────────────────────────────────────────────────────────────

describe('isClientError', () => {
  it('returns true for status 400', () => {
    expect(isClientError({ response: { status: 400 } })).toBe(true)
  })

  it('returns true for status 404', () => {
    expect(isClientError({ response: { status: 404 } })).toBe(true)
  })

  it('returns true for status 499', () => {
    expect(isClientError({ response: { status: 499 } })).toBe(true)
  })

  it('returns false for status 500', () => {
    expect(isClientError({ response: { status: 500 } })).toBe(false)
  })

  it('returns false for status 200', () => {
    expect(isClientError({ response: { status: 200 } })).toBe(false)
  })

  it('returns false for null', () => {
    expect(isClientError(null)).toBe(false)
  })

  it('returns false for undefined', () => {
    expect(isClientError(undefined)).toBe(false)
  })

  it('returns false for a non-object primitive', () => {
    expect(isClientError('some error string')).toBe(false)
  })

  it('returns false for an error object with no response property', () => {
    expect(isClientError({ message: 'Network Error' })).toBe(false)
  })

  it('returns false for an error with response but no status', () => {
    expect(isClientError({ response: {} })).toBe(false)
  })
})
