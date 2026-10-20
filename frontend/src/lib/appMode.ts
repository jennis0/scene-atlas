/**
 * App mode detection.
 *
 * 'app'    — running inside Electron (window.electronAPI is injected by the preload)
 * 'server' — running in a browser against a standalone uvicorn server
 *
 * This is a compile-time constant for the current session — it never changes
 * at runtime, so components can import it directly without a context/hook.
 *
 * Usage:
 *   import { appMode, isApp } from '@/lib/appMode'
 */

export type AppMode = 'app' | 'server'

export const appMode: AppMode =
  typeof window !== 'undefined' && !!window.electronAPI ? 'app' : 'server'

export const isApp = appMode === 'app'

/**
 * Who draws the window's title bar (design/electron.md#window-frame):
 *   'inset'   macOS: the page, around the traffic lights
 *   'overlay' Windows: the page, beside Electron's caption buttons (a 32px band)
 *   'native'  Linux and browsers: the system
 */
export type WindowChrome = 'inset' | 'overlay' | 'native'

const platform = typeof window !== 'undefined' ? window.electronAPI?.platform : undefined

export const windowChrome: WindowChrome = !isApp
  ? 'native'
  : platform === 'darwin'
    ? 'inset'
    : platform === 'win32'
      ? 'overlay'
      : 'native'

/** The window has no title bar, so pages must mark where it can be dragged. */
export const isFrameless = windowChrome !== 'native'

// The window's own controls keep their size whatever the zoom or text size, so the room
// left for them is in window pixels: CSS px divided by the zoom, which lib/zoom.ts
// publishes as --zoom. rem would grow with Text size, and plain px with zoom.

/** The band the Windows caption buttons cover (titleBarOverlay.height in electron/src/main.ts) */
export const TITLE_BAR_BAND = 'h-[calc(32px/var(--zoom,1))]'
/** Room beside the macOS traffic lights */
export const TRAFFIC_LIGHT_INSET = 'pl-[calc(80px/var(--zoom,1))]'
