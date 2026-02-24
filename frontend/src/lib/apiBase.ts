/**
 * Dynamic API base URL resolution for desktop (Electron) and dev modes.
 *
 * - Dev mode (Vite proxy): returns '/api/v1' — Vite proxies to localhost:8000
 * - Electron production: returns 'http://localhost:{port}/api/v1'
 *   where port is injected by the Electron main process via preload IPC
 */

export function getApiBaseUrl(): string {
  const port = window.__SCENE_ATLAS_PORT__
  return port ? `http://localhost:${port}/api/v1` : '/api/v1'
}

/**
 * Resolve a path-only API URL to a full URL.
 * Used for image/thumbnail src attributes that go into <img> tags (not axios).
 */
export function resolveApiUrl(path: string): string {
  const port = window.__SCENE_ATLAS_PORT__
  return port ? `http://localhost:${port}${path}` : path
}
