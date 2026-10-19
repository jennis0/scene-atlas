import { useSyncExternalStore } from 'react'
import { readPref, registerPref, writePref } from './prefsStorage'

/**
 * Desktop zoom (design/electron.md#zoom): scales the whole page, images included, as a
 * browser's zoom does. Text size scales only text and the spacing around it. In a browser
 * the browser's own zoom does this, so the choice is desktop only.
 *
 * The preload applies the saved zoom before the first paint; this keeps it from then on,
 * for the Settings control and the Ctrl + / − / 0 shortcuts alike.
 */
export const ZOOM_STORAGE_KEY = 'scene-atlas-zoom'
export const ZOOM_LEVELS = [80, 90, 100, 110, 125, 150, 175, 200] as const
export const DEFAULT_ZOOM = 100

registerPref(ZOOM_STORAGE_KEY)

function parse(raw: string | null): number {
  const value = Number(raw)
  return (ZOOM_LEVELS as readonly number[]).includes(value) ? value : DEFAULT_ZOOM
}

/** One level in (+1) or out (−1), clamped to the levels; 0 goes back to 100%. */
export function nextZoom(current: number, step: number): number {
  if (step === 0) return DEFAULT_ZOOM
  if (step > 0) return ZOOM_LEVELS.find((level) => level > current) ?? current
  return ZOOM_LEVELS.filter((level) => level < current).pop() ?? current
}

// Read lazily: the desktop's copy of the choices is synced into localStorage at startup,
// after this module loads.
let current: number | null = null
const listeners = new Set<() => void>()

export function getZoom(): number {
  if (current === null) current = parse(readPref(ZOOM_STORAGE_KEY))
  return current
}

/**
 * Zoom the page to *level*, and publish it as --zoom: the room left for the window's own
 * controls is sized in window pixels from it (TITLE_BAR_BAND in lib/appMode.ts). At
 * startup this re-applies the zoom the preload already set, to publish --zoom before the
 * first paint.
 */
export function applyZoom(level: number) {
  document.documentElement.style.setProperty('--zoom', String(level / 100))
  window.electronAPI?.setZoom?.(level)
}

export function setZoom(level: number) {
  const value = parse(String(level))
  current = value
  writePref(ZOOM_STORAGE_KEY, String(value))
  applyZoom(value)
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useZoom(): number {
  return useSyncExternalStore(subscribe, getZoom)
}

type ZoomKey = Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey'>

/** Ctrl (Cmd on macOS) with = or +, − or _, or 0: a step in, out, or back to 100%. */
export function zoomStepForKey(event: ZoomKey, mac: boolean): 1 | -1 | 0 | null {
  if (event.altKey || !(mac ? event.metaKey : event.ctrlKey)) return null
  if (event.key === '=' || event.key === '+') return 1
  if (event.key === '-' || event.key === '_') return -1
  if (event.key === '0') return 0
  return null
}

/**
 * Desktop: zoom on the shortcuts. Handled here, before the main process: preventing the
 * default keeps any menu accelerator for the same keys from firing too (the app's menus
 * have none: design/electron.md#menus). Returns the unsubscribe.
 */
export function listenForZoomKeys(): () => void {
  const api = window.electronAPI
  if (!api) return () => {}
  const mac = api.platform === 'darwin'
  const onKeyDown = (event: KeyboardEvent) => {
    const step = zoomStepForKey(event, mac)
    if (step === null) return
    event.preventDefault()
    setZoom(nextZoom(getZoom(), step))
  }
  window.addEventListener('keydown', onKeyDown)
  return () => window.removeEventListener('keydown', onKeyDown)
}
