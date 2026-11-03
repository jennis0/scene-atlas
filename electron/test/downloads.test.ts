import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import { showDownloadProgress } from '../src/downloads.ts'

function fakeItem(total: number) {
  const listeners: Record<string, () => void> = {}
  let received = 0
  return {
    item: {
      getReceivedBytes: () => received,
      getTotalBytes: () => total,
      on: (event: string, cb: () => void) => (listeners[event] = cb),
      once: (event: string, cb: () => void) => (listeners[event] = cb),
    },
    receive(bytes: number) {
      received = bytes
      listeners.updated()
    },
    finish: () => listeners.done(),
  }
}

function setup() {
  let onDownload: ((event: unknown, item: unknown) => void) | null = null
  const progress: number[] = []
  const win = { isDestroyed: () => false, setProgressBar: (p: number) => progress.push(p) }
  showDownloadProgress({ on: (_e: string, cb: typeof onDownload) => (onDownload = cb) }, () => win)
  return { progress, start: (item: unknown) => onDownload!({}, item) }
}

describe('showDownloadProgress', () => {
  test('shows the fraction received, then clears it when done', () => {
    const { progress, start } = setup()
    const download = fakeItem(200)
    start(download.item)
    download.receive(50)
    download.receive(200)
    download.finish()
    assert.deepEqual(progress, [0.25, 1, -1])
  })

  test('an unknown size shows as indeterminate', () => {
    const { progress, start } = setup()
    const download = fakeItem(0)
    start(download.item)
    download.receive(10)
    assert.deepEqual(progress, [2])
  })
})
