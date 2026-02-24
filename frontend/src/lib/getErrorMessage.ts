import { AxiosError } from 'axios'

/**
 * Extracts a human-readable error message from an unknown catch value.
 * Handles AxiosError (backend API errors), standard Error, and unknown values.
 */
export function getApiErrorMessage(err: unknown, fallback = 'An error occurred'): string {
  if (err instanceof AxiosError) {
    return err.response?.data?.detail ?? err.message ?? fallback
  }
  if (err instanceof Error) return err.message
  return fallback
}

/** Returns true when the error is an HTTP 404 Not Found response. */
export function isNotFoundError(err: unknown): boolean {
  return err instanceof AxiosError && err.response?.status === 404
}
