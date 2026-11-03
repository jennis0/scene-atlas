/**
 * The launch token (design/security.md §6d): a secret made once per run of the app, that
 * the backend requires on every request. Loopback is open to every user and program on
 * the computer; only this app's window (by its cookie) and this process (by the header)
 * have the token.
 */

import { randomBytes } from 'crypto'

/** The backend reads it from its environment (backend/app/host_check.py) */
export const TOKEN_ENV = 'SCENE_ATLAS_APP_TOKEN'
export const TOKEN_COOKIE = 'scene_atlas_token'
export const TOKEN_HEADER = 'X-Scene-Atlas-Token'

/**
 * A new token, or the one the app was started with in *env*. Whoever starts the app sets
 * its environment already; the packaged-app tests use this to call the API themselves.
 */
export function makeAppToken(env: NodeJS.ProcessEnv = process.env): string {
  const given = env[TOKEN_ENV]
  if (given && given.length >= 16) return given
  return randomBytes(32).toString('base64url')
}
