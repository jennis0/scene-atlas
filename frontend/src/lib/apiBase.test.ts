import { describe, it, expect, afterEach } from 'vitest'
import { getApiBaseUrl, resolveApiUrl } from './apiBase'

describe('getApiBaseUrl', () => {
  afterEach(() => {
    delete window.__SCENE_ATLAS_PORT__
  })

  it('returns relative path when no port is set (server mode)', () => {
    expect(getApiBaseUrl()).toBe('/api/v1')
  })

  it('returns absolute localhost URL when port is set (app mode)', () => {
    window.__SCENE_ATLAS_PORT__ = 12345
    expect(getApiBaseUrl()).toBe('http://localhost:12345/api/v1')
  })
})

describe('resolveApiUrl', () => {
  afterEach(() => {
    delete window.__SCENE_ATLAS_PORT__
  })

  it('returns path unchanged when no port is set', () => {
    expect(resolveApiUrl('/api/v1/images/1/file')).toBe('/api/v1/images/1/file')
  })

  it('prefixes with localhost:port when port is set', () => {
    window.__SCENE_ATLAS_PORT__ = 9000
    expect(resolveApiUrl('/api/v1/images/1/file')).toBe(
      'http://localhost:9000/api/v1/images/1/file',
    )
  })

  it('handles root-relative paths', () => {
    window.__SCENE_ATLAS_PORT__ = 8080
    expect(resolveApiUrl('/health')).toBe('http://localhost:8080/health')
  })
})
