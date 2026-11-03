/**
 * The launch token for the packaged-app and upgrade tests (design/security.md §6d). The
 * desktop app's backend refuses requests without it. The app takes the token it is
 * started with (SCENE_ATLAS_APP_TOKEN in its environment), so the tests choose one,
 * start the app with it, and send it on their own API calls.
 *
 * The browser E2E tests' backend runs without a token, so nothing is sent there.
 */
import { randomBytes } from "crypto";

const TOKEN_ENV = "SCENE_ATLAS_APP_TOKEN";

/** Choose this run's token: launch() passes it to the app through the environment. */
export function useAppToken(): string {
  process.env[TOKEN_ENV] ??= `packaged-test-${randomBytes(16).toString("hex")}`;
  return process.env[TOKEN_ENV];
}

/** The header that gets an API call in, once a token is chosen. */
export function tokenHeader(): Record<string, string> {
  const token = process.env[TOKEN_ENV];
  return token ? { "X-Scene-Atlas-Token": token } : {};
}
