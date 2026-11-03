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

/** Show each download's progress on the icon of the window *getWindow* returns. A size
 * the server didn't send shows as indeterminate (progress > 1). */
export function showDownloadProgress(
  session: SessionLike,
  getWindow: () => ProgressWindow | null,
): void {
  const show = (progress: number) => {
    const win = getWindow()
    if (win && !win.isDestroyed()) win.setProgressBar(progress)
  }
  session.on('will-download', (_event, item) => {
    item.on('updated', () => {
      const total = item.getTotalBytes()
      show(total > 0 ? item.getReceivedBytes() / total : 2)
    })
    item.once('done', () => show(-1))
  })
}
