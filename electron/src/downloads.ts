// Downloads (design/export-backup-move.md §5.2): Electron shows its save dialog by default
// but has no download UI of its own, so progress goes on the window's taskbar or dock icon.

/** The parts of Electron's DownloadItem this uses */
interface DownloadItemLike {
  getReceivedBytes(): number
  getTotalBytes(): number
  on(event: 'updated', listener: () => void): unknown
  once(event: 'done', listener: () => void): unknown
}

interface ProgressWindow {
  isDestroyed(): boolean
  setProgressBar(progress: number): void
}

interface SessionLike {
  on(event: 'will-download', listener: (event: unknown, item: DownloadItemLike) => void): unknown
}

/** Show the downloads' progress on the icon of the window *getWindow* returns: all of the
 * running ones together, cleared when the last ends (finished, cancelled or failed). A
 * size the server didn't send shows as indeterminate (progress > 1). */
export function showDownloadProgress(
  session: SessionLike,
  getWindow: () => ProgressWindow | null,
): void {
  const running = new Set<DownloadItemLike>()
  const show = () => {
    const win = getWindow()
    if (!win || win.isDestroyed()) return
    if (running.size === 0) return win.setProgressBar(-1)
    let received = 0
    let total = 0
    for (const item of running) {
      if (item.getTotalBytes() <= 0) return win.setProgressBar(2)
      received += item.getReceivedBytes()
      total += item.getTotalBytes()
    }
    win.setProgressBar(received / total)
  }
  session.on('will-download', (_event, item) => {
    running.add(item)
    item.on('updated', show)
    item.once('done', () => {
      running.delete(item)
      show()
    })
  })
}
