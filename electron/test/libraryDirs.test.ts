import { afterEach, beforeEach, describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import {
  dirsChanged,
  isFolderKind,
  isMissingOrEmpty,
  parseLibraryDirs,
  provisionalDirsToDelete,
  removeProvisionalDirs,
  unavailableLinkedError,
  type LibraryDirs,
} from '../src/libraryDirs.ts'

const win = {
  appData: 'C:\\Users\\sam\\AppData\\Local\\Scene Atlas\\data',
  store: 'C:\\Users\\sam\\AppData\\Local\\Scene Atlas\\images',
  linked: null,
}

describe('parseLibraryDirs', () => {
  test('accepts absolute folders and normalises them', () => {
    const result = parseLibraryDirs(
      { appData: '/home/sam/data/', store: '/home/sam/x/../images', linked: '/media/maps' },
      'linux',
    )
    assert.deepEqual(result, {
      dirs: { appData: '/home/sam/data', store: '/home/sam/images', linked: '/media/maps' },
    })
  })

  test('no linked folder is null, however it is sent', () => {
    for (const linked of [null, undefined, '']) {
      const result = parseLibraryDirs({ appData: '/a', store: '/b', linked }, 'linux')
      assert.deepEqual(result, { dirs: { appData: '/a', store: '/b', linked: null } })
    }
  })

  test('rejects relative, empty and missing paths, and other shapes', () => {
    for (const raw of [
      { appData: 'data', store: '/b', linked: null },
      { appData: '/a', store: '  ', linked: null },
      { appData: '/a', linked: null },
      { appData: '/a', store: '/b', linked: 'maps' },
      { appData: '/a', store: '/b', linked: 42 },
      null,
      'C:\\data',
    ]) {
      assert.ok('error' in parseLibraryDirs(raw, 'linux'), JSON.stringify(raw))
    }
  })

  test('the store and app data may sit inside the linked folder', () => {
    const result = parseLibraryDirs(
      { appData: win.appData, store: 'D:\\Battle Maps\\Scene Atlas', linked: 'D:\\Battle Maps' },
      'win32',
    )
    assert.ok('dirs' in result)
  })

  test('the store may not be the linked folder or contain it', () => {
    for (const store of ['D:\\Battle Maps', 'd:\\battle maps\\', 'D:\\']) {
      const result = parseLibraryDirs(
        { appData: win.appData, store, linked: 'D:\\Battle Maps' },
        'win32',
      )
      assert.match('error' in result ? result.error : '', /Imported maps folder/, store)
    }
  })

  test('app data may not be the linked folder or contain it', () => {
    const result = parseLibraryDirs(
      { appData: '/media', store: '/media/maps/Scene Atlas', linked: '/media/maps' },
      'linux',
    )
    assert.match('error' in result ? result.error : '', /Search data folder/)
  })
})

describe('dirsChanged', () => {
  test('the same folders, however written, are unchanged', () => {
    const same = { ...win, appData: win.appData.toUpperCase() + '\\' }
    assert.equal(dirsChanged(win, same, 'win32'), false)
  })

  test('any folder changing, or linking one, is a change', () => {
    assert.equal(dirsChanged(win, { ...win, store: 'E:\\Maps' }, 'win32'), true)
    assert.equal(dirsChanged(win, { ...win, appData: 'E:\\Data' }, 'win32'), true)
    assert.equal(dirsChanged(win, { ...win, linked: 'D:\\Maps' }, 'win32'), true)
    const linked = { ...win, linked: 'D:\\Maps' }
    assert.equal(dirsChanged(linked, { ...win, linked: null }, 'win32'), true)
    assert.equal(dirsChanged(linked, { ...win, linked: 'D:\\Other' }, 'win32'), true)
    assert.equal(dirsChanged(linked, { ...win, linked: 'd:\\maps' }, 'win32'), false)
  })

  test('case matters only where the file system ignores it', () => {
    const mac = { appData: '/Users/sam/SA/data', store: '/Users/sam/SA/images', linked: null }
    const renamed = { ...mac, store: '/Users/sam/sa/Images/' }
    assert.equal(dirsChanged(mac, renamed, 'darwin'), false)
    assert.equal(dirsChanged(mac, renamed, 'linux'), true)
  })
})

describe('provisionalDirsToDelete', () => {
  const provisional: LibraryDirs = {
    appData: '/home/sam/Documents/Scene Atlas/data',
    store: '/home/sam/Documents/Scene Atlas/images',
    linked: null,
  }
  const defaults = { appData: provisional.appData, store: provisional.store }

  test('both defaults replaced: both deleted', () => {
    const next = {
      appData: '/fast/data',
      store: '/media/maps/Scene Atlas',
      linked: '/media/maps',
    }
    assert.deepEqual(provisionalDirsToDelete(provisional, next, defaults, 'linux'), [
      provisional.appData,
      provisional.store,
    ])
  })

  test('a default that is kept is not deleted', () => {
    const next = { ...provisional, store: '/media/maps/Scene Atlas', linked: '/media/maps' }
    assert.deepEqual(provisionalDirsToDelete(provisional, next, defaults, 'linux'), [
      provisional.store,
    ])
  })

  test('a default that holds, or sits inside, a new folder is not deleted', () => {
    const next = {
      appData: '/home/sam/Documents/Scene Atlas/data/inner',
      store: '/home/sam/Documents',
      linked: null,
    }
    assert.deepEqual(provisionalDirsToDelete(provisional, next, defaults, 'linux'), [])
  })

  test('nothing inside the linked folder is deleted', () => {
    const next = { appData: '/fast/data', store: '/fast/images', linked: '/home/sam/Documents' }
    assert.deepEqual(provisionalDirsToDelete(provisional, next, defaults, 'linux'), [])
  })

  test('one folder for both is listed once', () => {
    const shared = { appData: '/sa', store: '/sa', linked: null }
    const next = { appData: '/new', store: '/new', linked: null }
    const sharedDefaults = { appData: '/sa', store: '/sa' }
    assert.deepEqual(provisionalDirsToDelete(shared, next, sharedDefaults, 'linux'), ['/sa'])
  })

  test('only the default folders are ever deleted', () => {
    // A config edited by hand to say provisional, on the user's own folders.
    const own = { appData: '/home/sam/Maps/data', store: '/home/sam/Maps', linked: null }
    const next = { appData: '/fast/data', store: '/fast/images', linked: null }
    assert.deepEqual(provisionalDirsToDelete(own, next, defaults, 'linux'), [])
  })

  test('paths differing only in case are the same folder on Windows', () => {
    const next = { ...win, appData: win.appData.toLowerCase(), store: 'E:\\Maps' }
    assert.deepEqual(provisionalDirsToDelete(win, next, win, 'win32'), [win.store])
  })
})

describe('isFolderKind', () => {
  test('only the three folder kinds', () => {
    for (const kind of ['appData', 'store', 'linked']) assert.equal(isFolderKind(kind), true)
    for (const kind of ['imageLibrary', '', null, 1]) assert.equal(isFolderKind(kind), false)
  })
})

describe('on disk', () => {
  let root: string

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'scene-atlas-library-'))
  })

  afterEach(() => {
    fs.rmSync(root, { recursive: true, force: true })
  })

  test('isMissingOrEmpty', () => {
    assert.equal(isMissingOrEmpty(path.join(root, 'none')), true)
    assert.equal(isMissingOrEmpty(root), true)
    fs.writeFileSync(path.join(root, 'file'), '')
    assert.equal(isMissingOrEmpty(root), false)
    // A file where the folder should be isn't "empty".
    assert.equal(isMissingOrEmpty(path.join(root, 'file')), false)
  })

  test('a store inside a missing linked folder is reported, not created', () => {
    const linked = path.join(root, 'unplugged')
    const dirs = {
      appData: path.join(root, 'data'),
      store: path.join(linked, 'Scene Atlas'),
      linked,
    }
    assert.match(unavailableLinkedError(dirs) ?? '', /isn't available/)
    fs.mkdirSync(linked)
    assert.equal(unavailableLinkedError(dirs), null)
  })

  test('removeProvisionalDirs deletes our own folders, then their empty parent', async () => {
    const base = path.join(root, 'Scene Atlas')
    const defaults = { appData: path.join(base, 'data'), store: path.join(base, 'images') }
    fs.mkdirSync(path.join(defaults.appData, 'lancedb'), { recursive: true })
    fs.writeFileSync(path.join(defaults.appData, 'battlemap.db'), '')
    fs.mkdirSync(path.join(defaults.store, 'ab', 'cd'), { recursive: true })
    await removeProvisionalDirs([defaults.appData, defaults.store], defaults)
    assert.equal(fs.existsSync(base), false)
  })

  test("removeProvisionalDirs keeps a folder holding anything that isn't ours", async () => {
    const base = path.join(root, 'Scene Atlas')
    const defaults = { appData: path.join(base, 'data'), store: path.join(base, 'images') }
    fs.mkdirSync(defaults.appData, { recursive: true })
    fs.mkdirSync(defaults.store, { recursive: true })
    fs.writeFileSync(path.join(defaults.store, 'Forest Clearing.png'), 'mine')
    await removeProvisionalDirs([defaults.appData, defaults.store], defaults)
    assert.equal(fs.existsSync(defaults.appData), false)
    assert.equal(fs.readFileSync(path.join(defaults.store, 'Forest Clearing.png'), 'utf8'), 'mine')
  })

  test('a missing linked folder elsewhere is fine: the backend shows it offline', () => {
    const dirs = {
      appData: path.join(root, 'data'),
      store: path.join(root, 'images'),
      linked: path.join(root, 'unplugged'),
    }
    assert.equal(unavailableLinkedError(dirs), null)
    assert.equal(unavailableLinkedError({ ...dirs, linked: null }), null)
  })
})
