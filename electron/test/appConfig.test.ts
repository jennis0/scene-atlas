import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import {
  firstLaunchConfig,
  libraryDirsOf,
  parseConfig,
  withChosenLibrary,
} from '../src/appConfig.ts'

const base = { appDataDir: '/sa/data', imageLibraryDir: '/sa/images' }

describe('parseConfig', () => {
  test('a config from before the setup wizard chose folders counts as chosen', () => {
    const result = parseConfig({ ...base }, 'linux')
    assert.equal(result?.migrated, false)
    assert.deepEqual(result?.config, {
      ...base,
      provisional: false,
      libraryChosen: true,
      displayPrefs: {},
    })
  })

  test('a provisional first-launch config is not chosen', () => {
    const result = parseConfig({ ...base, provisional: true, libraryChosen: false }, 'linux')
    assert.equal(result?.config.provisional, true)
    assert.equal(result?.config.libraryChosen, false)
  })

  test('libraryChosen is kept as written', () => {
    const result = parseConfig({ ...base, provisional: false, libraryChosen: true }, 'linux')
    assert.equal(result?.config.libraryChosen, true)
    assert.equal(parseConfig({ ...base, provisional: true }, 'linux')?.config.libraryChosen, false)
  })

  test('only provisional: true is provisional', () => {
    for (const provisional of ['true', 1, null, undefined]) {
      assert.equal(parseConfig({ ...base, provisional }, 'linux')?.config.provisional, false)
    }
  })

  test('keeps an absolute linked folder and drops anything else', () => {
    const linked = parseConfig({ ...base, linkedLibraryDir: '/media/maps' }, 'linux')
    assert.equal(linked?.config.linkedLibraryDir, '/media/maps')
    for (const linkedLibraryDir of ['maps', '', 42, null]) {
      const result = parseConfig({ ...base, linkedLibraryDir }, 'linux')
      assert.equal('linkedLibraryDir' in (result?.config ?? {}), false)
    }
    const winLinked = parseConfig({ ...base, linkedLibraryDir: 'D:\\Battle Maps' }, 'win32')
    assert.equal(winLinked?.config.linkedLibraryDir, 'D:\\Battle Maps')
  })

  test('keeps valid display choices and window colours', () => {
    const result = parseConfig(
      {
        ...base,
        displayPrefs: { 'scene-atlas-theme': 'dark', bad: 'x' },
        windowColors: { background: '#0e1118', foreground: '#ede8dc' },
        convertToWebp: true,
      },
      'linux',
    )
    assert.deepEqual(result?.config.displayPrefs, { 'scene-atlas-theme': 'dark' })
    assert.deepEqual(result?.config.windowColors, { background: '#0e1118', foreground: '#ede8dc' })
    assert.equal('convertToWebp' in (result?.config ?? {}), false)
  })

  test('migrates the single-root format', () => {
    const result = parseConfig({ dataDir: '/old' }, 'linux')
    assert.equal(result?.migrated, true)
    assert.deepEqual(result?.config, {
      appDataDir: '/old',
      imageLibraryDir: '/old/store/images',
      provisional: false,
      libraryChosen: true,
    })
  })

  test('an unusable config is null', () => {
    for (const raw of [
      null,
      [],
      'x',
      {},
      { appDataDir: '/a' },
      { appDataDir: 1, imageLibraryDir: '/b' },
    ]) {
      assert.equal(parseConfig(raw, 'linux'), null, JSON.stringify(raw))
    }
  })
})

describe('firstLaunchConfig', () => {
  const defaults = { appData: '/sa/data', store: '/sa/images' }

  test('the defaults, provisional and not yet chosen', () => {
    assert.deepEqual(firstLaunchConfig(defaults, true), {
      appDataDir: '/sa/data',
      imageLibraryDir: '/sa/images',
      provisional: true,
      libraryChosen: false,
    })
  })

  test('default folders that already hold something are never provisional', () => {
    // A library left at the defaults by an earlier install: replacing it mustn't delete it.
    assert.equal(firstLaunchConfig(defaults, false).provisional, false)
    assert.equal(firstLaunchConfig(defaults, false).libraryChosen, false)
  })
})

describe('withChosenLibrary', () => {
  const config = {
    ...base,
    linkedLibraryDir: '/old/maps',
    provisional: true,
    libraryChosen: false,
    displayPrefs: { 'scene-atlas-theme': 'dark' },
  }

  test('sets the folders and marks them chosen, keeping everything else', () => {
    const next = withChosenLibrary(config, { appData: '/d', store: '/m/SA', linked: '/m' })
    assert.deepEqual(next, {
      appDataDir: '/d',
      imageLibraryDir: '/m/SA',
      linkedLibraryDir: '/m',
      provisional: false,
      libraryChosen: true,
      displayPrefs: { 'scene-atlas-theme': 'dark' },
    })
  })

  test('keeping the defaults still ends provisional', () => {
    const next = withChosenLibrary(config, { ...libraryDirsOf(config), linked: null })
    assert.equal(next.provisional, false)
    assert.equal(next.libraryChosen, true)
    assert.equal('linkedLibraryDir' in next, false)
  })

  test('libraryDirsOf reads the folders back', () => {
    assert.deepEqual(libraryDirsOf(config), {
      appData: '/sa/data',
      store: '/sa/images',
      linked: '/old/maps',
    })
    assert.equal(libraryDirsOf({ ...base, provisional: false, libraryChosen: true }).linked, null)
  })
})
