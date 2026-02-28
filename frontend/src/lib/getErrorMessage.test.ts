import { describe, it, expect } from 'vitest'
import { AxiosError } from 'axios'
import { getApiErrorMessage, isNotFoundError } from './getErrorMessage'

// Helper to create an AxiosError with a response
function makeAxiosError(status: number, detail?: string): AxiosError {
  const error = new AxiosError('Request failed')
  error.response = {
    status,
    statusText: 'Error',
    headers: {},
    config: {} as never,
    data: detail !== undefined ? { detail } : {},
  }
  return error
}

describe('getApiErrorMessage', () => {
  it('extracts detail from AxiosError response', () => {
    const err = makeAxiosError(400, 'Invalid input')
    expect(getApiErrorMessage(err)).toBe('Invalid input')
  })

  it('falls back to err.message when no detail', () => {
    const err = makeAxiosError(500)
    expect(getApiErrorMessage(err)).toBe('Request failed')
  })

  it('returns message from standard Error', () => {
    const err = new Error('Something broke')
    expect(getApiErrorMessage(err)).toBe('Something broke')
  })

  it('returns fallback for unknown value', () => {
    expect(getApiErrorMessage('string error')).toBe('An error occurred')
    expect(getApiErrorMessage(null)).toBe('An error occurred')
    expect(getApiErrorMessage(42)).toBe('An error occurred')
  })

  it('uses custom fallback message', () => {
    expect(getApiErrorMessage(null, 'Custom fallback')).toBe('Custom fallback')
  })
})

describe('isNotFoundError', () => {
  it('returns true for AxiosError with status 404', () => {
    expect(isNotFoundError(makeAxiosError(404))).toBe(true)
  })

  it('returns false for AxiosError with other status', () => {
    expect(isNotFoundError(makeAxiosError(500))).toBe(false)
    expect(isNotFoundError(makeAxiosError(403))).toBe(false)
  })

  it('returns false for standard Error', () => {
    expect(isNotFoundError(new Error('not found'))).toBe(false)
  })

  it('returns false for null/undefined', () => {
    expect(isNotFoundError(null)).toBe(false)
    expect(isNotFoundError(undefined)).toBe(false)
  })
})
