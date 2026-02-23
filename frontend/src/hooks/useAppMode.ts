import { appMode, type AppMode } from '@/lib/appMode'

/**
 * Returns the current deployment mode: 'app' (Electron) or 'server' (browser).
 *
 * The value is stable for the lifetime of the session — no re-renders triggered.
 * Prefer the plain constants (isApp / isServer) for non-component code.
 */
export function useAppMode(): AppMode {
  return appMode
}
