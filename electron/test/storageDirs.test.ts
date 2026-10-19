import { afterEach, beforeEach, describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import {
  defaultStorageBase,
  hasForeignEntries,
  isSameOrInside,
  isSamePath,
  LIBRARY_MARKER,
  prepareStorageDirs,
} from '../src/storageDirs.ts'

let root: string

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'scene-atlas-storage-'))
})

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true })
})

function touch(...parts: string[]): void {
  const file = path.join(root, ...parts)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, '')
}

describe('hasForeignEntries', () => {
  test('an empty folder is fine', () => {
    assert.equal(hasForeignEntries(root), false)
  })

  test('a missing folder is fine (it will be created)', () => {
    assert.equal(hasForeignEntries(path.join(root, 'new')), false)
  })

  test('an existing image library is fine', () => {
    touch('ab', 'cd', 'abcd1234.webp')
    touch('backups', '20261018_010000', 'battlemap.db')
    touch('.backend.lock')
    touch('.incoming', 'x')
    assert.equal(hasForeignEntries(root), false)
  })

  test('an existing app data folder is fine', () => {
    for (const name of ['battlemap.db', 'battlemap.db-wal', 'logs/a.log', 'models/x', 'store/t']) {
      touch(...name.split('/'))
    }
    assert.equal(hasForeignEntries(root), false)
  })

  test('one folder holding both is fine', () => {
    touch('battlemap.db')
    touch('0f', '1e', 'key.png')
    assert.equal(hasForeignEntries(root), false)
  })

  test("the library marker is one of Scene Atlas's own entries", () => {
    touch(LIBRARY_MARKER)
    touch('battlemap.db')
    assert.equal(LIBRARY_MARKER, 'scene-atlas-library.json')
    assert.equal(hasForeignEntries(root), false)
  })

  test('OS clutter is ignored', () => {
    touch('desktop.ini')
    touch('Thumbs.db')
    touch('.DS_Store')
    assert.equal(hasForeignEntries(root), false)
  })

  test('a map collection is flagged', () => {
    touch('Forest Clearing [30x20].png')
    assert.equal(hasForeignEntries(root), true)
  })

  test('a non-shard subfolder is flagged', () => {
    touch('Dungeons', 'crypt.jpg')
    assert.equal(hasForeignEntries(root), true)
  })

  test('shard names are lower-case hex only', () => {
    touch('AB', 'x.png')
    assert.equal(hasForeignEntries(root), true)
  })

  test('the other storage folder, or a folder containing it, is expected', () => {
    const appData = path.join(root, 'Scene Atlas', 'data')
    fs.mkdirSync(appData, { recursive: true })
    assert.equal(hasForeignEntries(root, appData), false)
    assert.equal(hasForeignEntries(root, path.join(root, 'elsewhere')), true)
  })
})

describe('defaultStorageBase', () => {
  const dirs = { home: 'C:\\Users\\sam', documents: 'C:\\Users\\sam\\OneDrive\\Documents' }

  test('Windows uses Local AppData, never the (possibly OneDrive) Documents folder', () => {
    const env = { LOCALAPPDATA: 'C:\\Users\\sam\\AppData\\Local' }
    assert.equal(
      defaultStorageBase('win32', env, dirs),
      'C:\\Users\\sam\\AppData\\Local\\Scene Atlas',
    )
  })

  test('Windows falls back to the standard Local AppData path', () => {
    for (const LOCALAPPDATA of [undefined, '', 'relative\\dir']) {
      assert.equal(
        defaultStorageBase('win32', { LOCALAPPDATA }, dirs),
        'C:\\Users\\sam\\AppData\\Local\\Scene Atlas',
      )
    }
  })

  test('macOS and Linux use Documents', () => {
    const unix = { home: '/home/sam', documents: '/home/sam/Documents' }
    assert.equal(
      defaultStorageBase('linux', {}, unix),
      path.join('/home/sam/Documents', 'Scene Atlas'),
    )
    assert.equal(
      defaultStorageBase('darwin', {}, unix),
      path.join('/home/sam/Documents', 'Scene Atlas'),
    )
  })
})

describe('prepareStorageDirs', () => {
  test('creates both folders', () => {
    const a = path.join(root, 'data')
    const b = path.join(root, 'images')
    assert.equal(prepareStorageDirs(a, b), null)
    assert.ok(fs.statSync(a).isDirectory())
    assert.ok(fs.statSync(b).isDirectory())
  })

  test('allows one folder for both', () => {
    assert.equal(prepareStorageDirs(root, root), null)
  })

  test('reports a folder that cannot be created', () => {
    touch('file')
    const error = prepareStorageDirs(path.join(root, 'file', 'data'), root)
    assert.match(error ?? '', /^Search data folder can't be used/)
  })
})

describe('isSameOrInside', () => {
  test('a folder is inside itself and its parents, not its siblings', () => {
    assert.equal(isSameOrInside('/maps', '/maps', 'linux'), true)
    assert.equal(isSameOrInside('/maps/Scene Atlas', '/maps', 'linux'), true)
    assert.equal(isSameOrInside('/maps', '/maps/Scene Atlas', 'linux'), false)
    assert.equal(isSameOrInside('/maps2', '/maps', 'linux'), false)
    assert.equal(isSameOrInside('/..maps', '/', 'linux'), true)
  })

  test('trailing separators and dot segments are normalised', () => {
    assert.equal(isSameOrInside('/maps/a/../b/', '/maps/', 'linux'), true)
    assert.equal(isSamePath('/maps/', '/maps', 'linux'), true)
  })

  test('Windows and macOS compare case-insensitively, Linux does not', () => {
    assert.equal(isSamePath('D:\\Battle Maps', 'd:\\battle maps', 'win32'), true)
    assert.equal(isSameOrInside('D:\\Maps\\Scene Atlas', 'd:\\maps', 'win32'), true)
    assert.equal(isSameOrInside('D:\\Maps', 'E:\\Maps', 'win32'), false)
    assert.equal(isSamePath('/Users/sam/Maps', '/users/sam/maps', 'darwin'), true)
    assert.equal(isSamePath('/home/sam/Maps', '/home/sam/maps', 'linux'), false)
  })
})
