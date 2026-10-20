import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import {
  firstLaunchConfig,
  libraryDirsOf,
  parseConfig,
  withChosenLibrary,
  withDefaultLibrary,
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

  test('libraryChosen as written wins; without it, a provisional config is not chosen', () => {
    // Choose folders… on defaults that aren't empty: not provisional, but not chosen either.
    const back = parseConfig({ ...base, provisional: false, libraryChosen: false }, 'linux')
    assert.equal(back?.config.libraryChosen, false)
    const first = parseConfig({ ...base, provisional: true }, 'linux')
    assert.equal(first?.config.provisional, true)
    assert.equal(first?.config.libraryChosen, false)
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

  test("keeps the window state and update choice, so saving the config doesn't drop them", () => {
    const windowState = { x: 10, y: 20, width: 1200, height: 800, maximized: false }
    const result = parseConfig({ ...base, windowState, updateChoice: 'off' }, 'linux')
    assert.deepEqual(result?.config.windowState, windowState)
    assert.equal(result?.config.updateChoice, 'off')
    // 0.1.x's checkForUpdates: false is read as Off
    assert.equal(
      parseConfig({ ...base, checkForUpdates: false }, 'linux')?.config.updateChoice,
      'off',
    )
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

describe('withDefaultLibrary', () => {
  const defaults = { appData: '/sa/data', store: '/sa/images' }
  const refused = {
    appDataDir: '/elsewhere/data',
    imageLibraryDir: '/mnt/maps/Scene Atlas',
    linkedLibraryDir: '/mnt/maps',
    provisional: false,
    libraryChosen: true,
    displayPrefs: { 'scene-atlas-theme': 'dark' },
  }

  test('back on the defaults, with the library step to show again', () => {
    assert.deepEqual(withDefaultLibrary(refused, defaults, true), {
      appDataDir: '/sa/data',
      imageLibraryDir: '/sa/images',
      provisional: true,
      libraryChosen: false,
      displayPrefs: { 'scene-atlas-theme': 'dark' },
    })
  })

  test('defaults that already hold something are never provisional', () => {
    assert.equal(withDefaultLibrary(refused, defaults, false).provisional, false)
  })
})
