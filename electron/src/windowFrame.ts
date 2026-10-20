// How the app's windows look and where the main one opens: the frame per platform, the
// menus, the starting colours, and the main window's remembered size and position
// (design/electron.md#window-frame). main.ts creates the windows.
import { BrowserWindow, Menu, nativeTheme, screen } from 'electron'
import { loadConfig, updateConfig } from './config'
import { MIN_SIZE, restoredBounds, type OpenBounds } from './windowState'

const isMac = process.platform === 'darwin'
const isWindows = process.platform === 'win32'
const isLinux = process.platform === 'linux'

/** The colours a new window starts in: the UI's last reported ones, else the navy palette's
 * page background and text (frontend/src/index.css) for the current light/dark. */
function windowColors(): { background: string; foreground: string } {
  const saved = loadConfig()?.windowColors
  if (saved) return saved
  return nativeTheme.shouldUseDarkColors
    ? { background: '#0e1118', foreground: '#ede8dc' }
    : { background: '#eee9e2', foreground: '#2b2622' }
}

/**
 * The window frame: borderless with the traffic lights inset on macOS, borderless with
 * Electron's caption buttons on Windows. Linux keeps the window manager's title bar, which
 * matches the desktop and its scaling; Electron draws GNOME-style buttons there that look
 * wrong on any other desktop.
 */
export function frameOptions(): Partial<Electron.BrowserWindowConstructorOptions> {
  const { background, foreground } = windowColors()
  if (isLinux) return { backgroundColor: background }
  return {
    backgroundColor: background,
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    ...(isWindows && {
      titleBarOverlay: {
        color: background,
        symbolColor: foreground,
        height: 32,
      },
    }),
  }
}

/** The Windows title-bar overlay follows the UI's colours (window:set-colors). */
export function setTitleBarColors(win: BrowserWindow, background: string, foreground: string) {
  win.setBackgroundColor(background)
  if (isWindows) win.setTitleBarOverlay({ color: background, symbolColor: foreground })
}

/**
 * Menus (design/electron.md#menus). Electron's default menu has zoom shortcuts of its own,
 * which change the zoom without saving it (the UI keeps zoom: lib/zoom.ts), and Reload and
 * Toggle Developer Tools, which a release shouldn't have. Windows and Linux need no menu:
 * Chromium handles copy and paste itself, and on Linux the frame would show it as a bar.
 * macOS needs one for the app, Edit and Window commands, so it gets those only.
 */
export function removeMenu(win: BrowserWindow): void {
  if (!isMac) win.removeMenu()
}

export function setMacMenu(): void {
  if (!isMac) return
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      { role: 'appMenu' },
      { role: 'editMenu' },
      { label: 'View', submenu: [{ role: 'togglefullscreen' }] },
      { role: 'windowMenu' },
    ]),
  )
}

/** The screens' work areas, the primary first (windowState.ts). */
function workAreas(): Electron.Rectangle[] {
  const primary = screen.getPrimaryDisplay()
  const others = screen.getAllDisplays().filter((d) => d.id !== primary.id)
  return [primary, ...others].map((d) => d.workArea)
}

/** Where the main window opens, from its saved state (design/electron.md#window-state). */
export function mainWindowPlacement(): {
  bounds: OpenBounds & { minWidth: number; minHeight: number }
  maximized: boolean
} {
  const saved = loadConfig()?.windowState ?? null
  return {
    bounds: {
      ...restoredBounds(saved, workAreas()),
      minWidth: MIN_SIZE.width,
      minHeight: MIN_SIZE.height,
    },
    maximized: saved?.maximized ?? false,
  }
}

/** Save the window's size, position and maximised state as the user changes them. */
export function rememberWindowState(win: BrowserWindow): void {
  let timer: NodeJS.Timeout | undefined
  const save = () => {
    clearTimeout(timer)
    if (win.isDestroyed()) return
    // The bounds it un-maximises to, so a maximised window still remembers its size.
    updateConfig({ windowState: { ...win.getNormalBounds(), maximized: win.isMaximized() } })
  }
  const saveSoon = () => {
    clearTimeout(timer)
    timer = setTimeout(save, 1000)
  }
  win.on('resize', saveSoon)
  win.on('move', saveSoon)
  win.on('maximize', save)
  win.on('unmaximize', save)
  win.on('close', save)
}
