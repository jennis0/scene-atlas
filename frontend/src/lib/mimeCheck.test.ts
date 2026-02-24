import { describe, it, expect } from 'vitest'
import { filterByMagicBytes } from './mimeCheck'

/** Build a mock File with the given magic bytes padded to 12 bytes. */
function makeFile(name: string, bytes: number[]): File {
  const padded = [...bytes, ...Array(Math.max(0, 12 - bytes.length)).fill(0)]
  const buf = new Uint8Array(padded)
  return new File([buf], name)
}

describe('filterByMagicBytes', () => {
  it('accepts JPEG files (FF D8 FF)', async () => {
    const file = makeFile('photo.jpg', [0xff, 0xd8, 0xff, 0xe0])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('accepts PNG files (89 50 4E 47...)', async () => {
    const file = makeFile('image.png', [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('accepts GIF files (47 49 46 38)', async () => {
    const file = makeFile('anim.gif', [0x47, 0x49, 0x46, 0x38, 0x39, 0x61])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('accepts WebP files (RIFF....WEBP)', async () => {
    const file = makeFile('image.webp', [
      0x52,
      0x49,
      0x46,
      0x46, // RIFF
      0x00,
      0x00,
      0x00,
      0x00, // file size (arbitrary)
      0x57,
      0x45,
      0x42,
      0x50, // WEBP
    ])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('accepts MP4 files (ftyp at offset 4)', async () => {
    const file = makeFile('video.mp4', [
      0x00,
      0x00,
      0x00,
      0x00, // box size
      0x66,
      0x74,
      0x79,
      0x70, // ftyp
    ])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('accepts WebM files (1A 45 DF A3)', async () => {
    const file = makeFile('video.webm', [0x1a, 0x45, 0xdf, 0xa3])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('accepts ZIP files (PK\\x03\\x04)', async () => {
    const file = makeFile('archive.zip', [0x50, 0x4b, 0x03, 0x04])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('accepts empty ZIP (PK\\x05\\x06)', async () => {
    const file = makeFile('empty.zip', [0x50, 0x4b, 0x05, 0x06])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(1)
    expect(skipped).toHaveLength(0)
  })

  it('rejects files with unknown magic bytes', async () => {
    const file = makeFile('bad.txt', [0x00, 0x00, 0x00, 0x00])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(0)
    expect(skipped).toEqual(['bad.txt'])
  })

  it('separates valid and invalid files from a mixed batch', async () => {
    const jpeg = makeFile('ok.jpg', [0xff, 0xd8, 0xff])
    const bad = makeFile('bad.exe', [0x4d, 0x5a]) // MZ header
    const png = makeFile('also.png', [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    const { valid, skipped } = await filterByMagicBytes([jpeg, bad, png])
    expect(valid).toHaveLength(2)
    expect(skipped).toEqual(['bad.exe'])
  })

  it('handles an empty array', async () => {
    const { valid, skipped } = await filterByMagicBytes([])
    expect(valid).toHaveLength(0)
    expect(skipped).toHaveLength(0)
  })

  it('does not misidentify RIFF without WEBP signature as valid', async () => {
    // RIFF header but for WAV, not WebP
    const file = makeFile('audio.wav', [
      0x52,
      0x49,
      0x46,
      0x46, // RIFF
      0x00,
      0x00,
      0x00,
      0x00,
      0x57,
      0x41,
      0x56,
      0x45, // WAVE (not WEBP)
    ])
    const { valid, skipped } = await filterByMagicBytes([file])
    expect(valid).toHaveLength(0)
    expect(skipped).toEqual(['audio.wav'])
  })
})
