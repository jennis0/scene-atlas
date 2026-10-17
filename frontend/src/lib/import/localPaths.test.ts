import { afterEach, describe, expect, it, vi } from 'vitest'
import { canImportLocally, chooseLocalPaths, pathsFromDrop } from './localPaths'

function dropOf(names: string[]): DataTransfer {
  const files = names.map((n) => new File([], n))
  return { files } as unknown as DataTransfer
}

function installElectron(pathFor: (file: File) => string) {
  window.electronAPI = {
    getPathForFile: vi.fn(pathFor),
    chooseImportFolders: vi.fn(async () => ['/maps/Forest']),
    chooseImportFiles: vi.fn(async () => ['/maps/a.png', '/maps/b.png']),
  } as unknown as NonNullable<Window['electronAPI']>
}

afterEach(() => {
  delete window.electronAPI
})

describe('local paths', () => {
  it('are unavailable in a browser', async () => {
    expect(canImportLocally()).toBe(false)
    expect(pathsFromDrop(dropOf(['a.png']))).toBeNull()
    expect(await chooseLocalPaths('folders')).toEqual([])
  })

  it('come from the top-level dropped items in the desktop app', () => {
    installElectron((f) => `/maps/${f.name}`)
    expect(canImportLocally()).toBe(true)
    expect(pathsFromDrop(dropOf(['Forest', 'Cave.zip']))).toEqual([
      '/maps/Forest',
      '/maps/Cave.zip',
    ])
  })

  it('fall back to uploading when any dropped item has no path', () => {
    installElectron((f) => (f.name === 'pasted.png' ? '' : `/maps/${f.name}`))
    expect(pathsFromDrop(dropOf(['Forest', 'pasted.png']))).toBeNull()
    expect(pathsFromDrop(dropOf([]))).toBeNull()
  })

  it('come from the native pickers', async () => {
    installElectron(() => '')
    expect(await chooseLocalPaths('folders')).toEqual(['/maps/Forest'])
    expect(await chooseLocalPaths('files')).toEqual(['/maps/a.png', '/maps/b.png'])
  })
})
