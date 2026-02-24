/**
 * Client-side SHA-256 hashing using the native Web Crypto API.
 *
 * Files are read as ArrayBuffers and hashed via crypto.subtle.digest.
 * Processed sequentially to avoid loading multiple large battlemaps
 * (10-50 MB each) into memory simultaneously.
 */

export interface HashProgress {
  current: number
  total: number
  currentFileName: string
}

export interface HashedFile {
  file: File
  relativePath: string
  contentHash: string
}

async function hashSingleFile(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer)
  const bytes = new Uint8Array(hashBuffer)
  const hex: string[] = []
  for (let i = 0; i < bytes.length; i++) {
    hex.push(bytes[i].toString(16).padStart(2, '0'))
  }
  return hex.join('')
}

/**
 * Hash multiple files sequentially with progress reporting.
 */
export async function hashFiles(
  files: File[],
  getRelativePath: (file: File, index: number) => string,
  onProgress?: (progress: HashProgress) => void,
): Promise<HashedFile[]> {
  const results: HashedFile[] = []
  for (let i = 0; i < files.length; i++) {
    onProgress?.({
      current: i,
      total: files.length,
      currentFileName: files[i].name,
    })
    const contentHash = await hashSingleFile(files[i])
    results.push({
      file: files[i],
      relativePath: getRelativePath(files[i], i),
      contentHash,
    })
  }
  return results
}
