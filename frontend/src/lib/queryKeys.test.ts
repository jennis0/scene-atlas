import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { QueryClient } from '@tanstack/react-query'
import {
  QUERY_KEYS,
  invalidateGalleryQueries,
  invalidateTagQueries,
  refreshGalleryInPlace,
} from './queryKeys'

const SRC = resolve(__dirname, '..')

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : []
  })
}

describe('query keys', () => {
  it('are never written inline, so invalidations cannot drift from the queries', () => {
    // A literal like queryKey: ['tag-categories'] silently matches nothing when the
    // real key is spelled differently.
    const offenders = sourceFiles(SRC)
      .filter((file) => /queryKey:\s*\[\s*['"`]/.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SRC, file))
    expect(offenders).toEqual([])
  })

  it('invalidateTagQueries hits the tag-category and facet queries', () => {
    const client = new QueryClient()
    client.setQueryData(QUERY_KEYS.tagCategories, [])
    client.setQueryData(QUERY_KEYS.searchFacets, {})
    invalidateTagQueries(client)
    expect(client.getQueryState(QUERY_KEYS.tagCategories)?.isInvalidated).toBe(true)
    expect(client.getQueryState(QUERY_KEYS.searchFacets)?.isInvalidated).toBe(true)
  })

  it('invalidateGalleryQueries hits parameterised search queries by prefix', () => {
    const client = new QueryClient()
    client.setQueryData([...QUERY_KEYS.search, { query: 'x' }], {})
    invalidateGalleryQueries(client)
    expect(client.getQueryState([...QUERY_KEYS.search, { query: 'x' }])?.isInvalidated).toBe(true)
  })

  it('refreshGalleryInPlace keeps the results on screen and trims grouped pages to the first', () => {
    const client = new QueryClient()
    const searchKey = [...QUERY_KEYS.search, { query: 'x' }]
    const groupsKey = [...QUERY_KEYS.groups, { sort_by: 'created_at' }]
    client.setQueryData(searchKey, { images: [1] })
    client.setQueryData(groupsKey, { pages: ['p0', 'p1', 'p2'], pageParams: [0, 50, 100] })

    refreshGalleryInPlace(client)

    expect(client.getQueryData(searchKey)).toEqual({ images: [1] })
    expect(client.getQueryState(searchKey)?.isInvalidated).toBe(true)
    expect(client.getQueryData(groupsKey)).toEqual({ pages: ['p0'], pageParams: [0] })
    expect(client.getQueryState(groupsKey)?.isInvalidated).toBe(true)
  })
})
