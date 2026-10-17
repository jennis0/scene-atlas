/**
 * Client-side hashing used to skip uploading files the library already has.
 *
 * The client hash is only ever used to *skip* an upload; the server re-hashes
 * every byte it receives. So when hashing isn't possible we simply don't hash
 * and let the server deduplicate after upload:
 *
 * - `crypto.subtle` only exists in secure contexts (HTTPS or localhost), so a
 *   plain-HTTP LAN deployment gets no client hashing.
 * - Very large files are skipped: `subtle.digest` needs the whole file in memory.
 */

/** Largest file hashed client-side. */
const MAX_CLIENT_HASH_BYTES = 256 * 1024 * 1024

export interface Hasher {
  /** SHA-256 hex digest, or null if this file can't or shouldn't be hashed here. */
  hash(file: File): Promise<string | null>
  dispose(): void
}

const noopHasher: Hasher = {
  hash: async () => null,
  dispose: () => {},
}

/** Hashes in a dedicated Web Worker, one file at a time. */
class WorkerHasher implements Hasher {
  private worker: Worker
  private nextId = 0
  private pending = new Map<number, { resolve: (h: string | null) => void }>()

  constructor() {
    this.worker = new Worker(new URL('./hash.worker.ts', import.meta.url), { type: 'module' })
    this.worker.onmessage = (
      event: MessageEvent<{ id: number; hash?: string; error?: string }>,
    ) => {
      const entry = this.pending.get(event.data.id)
      this.pending.delete(event.data.id)
      entry?.resolve(event.data.hash ?? null) // on error, fall back to server-side dedup
    }
    this.worker.onerror = () => {
      for (const entry of this.pending.values()) entry.resolve(null)
      this.pending.clear()
    }
  }

  hash(file: File): Promise<string | null> {
    if (file.size > MAX_CLIENT_HASH_BYTES) return Promise.resolve(null)
    const id = this.nextId++
    return new Promise((resolve) => {
      this.pending.set(id, { resolve })
      this.worker.postMessage({ id, file })
    })
  }

  dispose(): void {
    this.worker.terminate()
    for (const entry of this.pending.values()) entry.resolve(null)
    this.pending.clear()
  }
}

/** The best hasher available in this browser context. */
export function createHasher(): Hasher {
  const canHash =
    typeof Worker !== 'undefined' &&
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    typeof crypto !== 'undefined' &&
    !!crypto.subtle
  if (!canHash) return noopHasher
  try {
    return new WorkerHasher()
  } catch {
    return noopHasher
  }
}
