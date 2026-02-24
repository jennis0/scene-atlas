/**
 * Client-side file type detection via magic bytes.
 *
 * Reads only the first 12 bytes of each File object — fast and non-blocking
 * regardless of file size. All checks run in parallel via Promise.all.
 *
 * Supported signatures:
 *   JPEG   FF D8 FF
 *   PNG    89 50 4E 47 0D 0A 1A 0A
 *   GIF    47 49 46 38 (GIF8...)
 *   WebP   52 49 46 46 ?? ?? ?? ?? 57 45 42 50  (RIFF....WEBP)
 *   MP4    ?? ?? ?? ?? 66 74 79 70  ('ftyp' at offset 4)
 *   WebM   1A 45 DF A3  (EBML header)
 *   ZIP    50 4B 03 04  (local file header)
 *          50 4B 05 06  (end-of-central-directory, empty archive)
 */

const HEADER_BYTES = 12

type KnownFormat = 'image' | 'video' | 'zip' | 'unknown'

function matchBytes(header: Uint8Array, offset: number, expected: number[]): boolean {
  return expected.every((b, i) => header[offset + i] === b)
}

async function readHeader(file: File): Promise<Uint8Array> {
  const buf = await file.slice(0, HEADER_BYTES).arrayBuffer()
  return new Uint8Array(buf)
}

function classifyHeader(header: Uint8Array): KnownFormat {
  // JPEG: FF D8 FF
  if (matchBytes(header, 0, [0xff, 0xd8, 0xff])) return 'image'

  // PNG: 89 50 4E 47 0D 0A 1A 0A
  if (matchBytes(header, 0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'image'

  // GIF: GIF8 (GIF87a or GIF89a)
  if (matchBytes(header, 0, [0x47, 0x49, 0x46, 0x38])) return 'image'

  // WebP: RIFF at 0-3, WEBP at 8-11
  if (
    matchBytes(header, 0, [0x52, 0x49, 0x46, 0x46]) &&
    matchBytes(header, 8, [0x57, 0x45, 0x42, 0x50])
  ) {
    return 'image'
  }

  // MP4/MOV: 'ftyp' at bytes 4-7
  if (matchBytes(header, 4, [0x66, 0x74, 0x79, 0x70])) return 'video'

  // WebM: EBML header 1A 45 DF A3
  if (matchBytes(header, 0, [0x1a, 0x45, 0xdf, 0xa3])) return 'video'

  // ZIP local-file-header: PK\x03\x04
  if (matchBytes(header, 0, [0x50, 0x4b, 0x03, 0x04])) return 'zip'

  // ZIP end-of-central-directory (empty archive): PK\x05\x06
  if (matchBytes(header, 0, [0x50, 0x4b, 0x05, 0x06])) return 'zip'

  return 'unknown'
}

/**
 * Check every file's magic bytes in parallel (reads only 12 bytes each).
 * Returns valid files (image or ZIP) and the names of any that were rejected.
 */
export async function filterByMagicBytes(
  files: File[],
): Promise<{ valid: File[]; skipped: string[] }> {
  const headers = await Promise.all(files.map(readHeader))
  const valid: File[] = []
  const skipped: string[] = []
  for (let i = 0; i < files.length; i++) {
    if (classifyHeader(headers[i]) !== 'unknown') {
      valid.push(files[i])
    } else {
      skipped.push(files[i].name)
    }
  }
  return { valid, skipped }
}
