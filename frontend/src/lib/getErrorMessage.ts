import { AxiosError } from 'axios'

const MAX_MESSAGE_LENGTH = 500

/** Truncate a message to {@link MAX_MESSAGE_LENGTH} chars, appending "…" if cut. */
function truncate(message: string): string {
  if (message.length <= MAX_MESSAGE_LENGTH) return message
  return message.slice(0, MAX_MESSAGE_LENGTH) + '…'
}

/**
 * Extracts a human-readable error message from an unknown catch value.
 * Handles AxiosError (backend API errors), standard Error, and unknown values.
 *
 * Messages are truncated to 500 characters to avoid leaking verbose
 * backend internals (SQL errors, stack traces, file paths) to the UI.
 */
export function getApiErrorMessage(err: unknown, fallback = 'An error occurred'): string {
  if (err instanceof AxiosError) {
    return truncate(err.response?.data?.detail ?? err.message ?? fallback)
  }
  if (err instanceof Error) return truncate(err.message)
  return fallback
}

/** Returns true when the error is an HTTP 404 Not Found response. */
export function isNotFoundError(err: unknown): boolean {
  return err instanceof AxiosError && err.response?.status === 404
}

/** Returns true when the error is an HTTP 409 Conflict response. */
export function isConflictError(err: unknown): boolean {
  return err instanceof AxiosError && err.response?.status === 409
}
