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
