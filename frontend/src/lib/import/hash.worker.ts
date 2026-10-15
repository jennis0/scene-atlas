/// <reference lib="webworker" />
/**
 * SHA-256 of a File, off the main thread.
 *
 * Message in:  { id: number, file: File }
 * Message out: { id: number, hash: string } | { id: number, error: string }
 */

self.onmessage = async (event: MessageEvent<{ id: number; file: File }>) => {
  const { id, file } = event.data
  try {
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    const hash = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
    self.postMessage({ id, hash })
  } catch (err) {
    self.postMessage({ id, error: err instanceof Error ? err.message : String(err) })
  }
}

export {}
