import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import {
  canCheck,
  DEFAULT_UPDATE_CHOICE,
  parseFeedOverride,
  parseUpdateChoice,
  releasePageUrl,
  savedUpdateChoice,
  updateModeFor,
  updaterBehaviour,
  wholePercent,
  type UpdateStatus,
} from '../src/updatePolicy.ts'

describe('updateModeFor', () => {
  test('installs on Windows', () => {
    assert.equal(updateModeFor('win32', {}), 'install')
  })

  test('installs from an AppImage, only notifies for a .deb', () => {
    assert.equal(updateModeFor('linux', { APPIMAGE: '/home/u/Scene-Atlas.AppImage' }), 'install')
    assert.equal(updateModeFor('linux', {}), 'notify')
    assert.equal(updateModeFor('linux', { APPIMAGE: '' }), 'notify')
  })

  test('only notifies on macOS: unsigned builds cannot install', () => {
    assert.equal(updateModeFor('darwin', {}), 'notify')
    assert.equal(updateModeFor('darwin', { APPIMAGE: '/x' }), 'notify')
  })
})

describe('parseFeedOverride', () => {
  test('accepts plain http on the loopback address', () => {
    assert.equal(parseFeedOverride('http://127.0.0.1:8123/'), 'http://127.0.0.1:8123/')
    assert.equal(parseFeedOverride('http://127.0.0.1:8123/feed'), 'http://127.0.0.1:8123/feed')
  })

  test('rejects anything that could reach another machine', () => {
    for (const raw of [
      'https://127.0.0.1:8123/',
      'http://localhost:8123/',
      'http://example.com/',
      'http://127.0.0.1.example.com/',
      'http://user:pw@127.0.0.1:8123/',
      'file:///C:/feed',
      'not a url',
    ]) {
      assert.equal(parseFeedOverride(raw), null, raw)
    }
  })

  test('is null when unset', () => {
    assert.equal(parseFeedOverride(undefined), null)
    assert.equal(parseFeedOverride(''), null)
  })
})

describe('releasePageUrl', () => {
  test('links to the version\u2019s release', () => {
    assert.equal(
      releasePageUrl('0.2.0'),
      'https://github.com/jennis0/scene-atlas/releases/tag/v0.2.0',
    )
    assert.equal(
      releasePageUrl('1.0.0-beta.1'),
      'https://github.com/jennis0/scene-atlas/releases/tag/v1.0.0-beta.1',
    )
    assert.equal(
      releasePageUrl('1.0.0-rc-2'),
      'https://github.com/jennis0/scene-atlas/releases/tag/v1.0.0-rc-2',
    )
  })

  test('falls back to the releases list for anything that is not a version', () => {
    for (const version of [
      undefined,
      '',
      '1.0',
      '1.0.0-',
      '1.0.0-beta/1',
      'x1.0.0-beta',
      '1.0.0/../../evil',
      '1.0.0?x=1',
    ]) {
      assert.equal(releasePageUrl(version), 'https://github.com/jennis0/scene-atlas/releases')
    }
  })
})

describe('canCheck', () => {
  test('only from a settled state', () => {
    const allowed: UpdateStatus[] = ['idle', 'up-to-date', 'error']
    const blocked: UpdateStatus[] = ['unsupported', 'checking', 'available', 'downloading', 'ready']
    for (const status of allowed) assert.equal(canCheck(status), true, status)
    for (const status of blocked) assert.equal(canCheck(status), false, status)
  })
})

describe('wholePercent', () => {
  test('floors and clamps', () => {
    assert.equal(wholePercent(42.9), 42)
    assert.equal(wholePercent(-3), 0)
    assert.equal(wholePercent(140), 100)
  })

  test('treats a missing value as 0', () => {
    for (const raw of [undefined, null, NaN, '50']) assert.equal(wholePercent(raw), 0)
  })
})

describe('update choice', () => {
  test('the default asks first', () => {
    assert.equal(DEFAULT_UPDATE_CHOICE, 'ask')
  })

  test('parses only the three choices', () => {
    for (const choice of ['automatic', 'ask', 'off'])
      assert.equal(parseUpdateChoice(choice), choice)
    for (const raw of [undefined, null, '', 'Automatic', 'on', true, 1]) {
      assert.equal(parseUpdateChoice(raw), null, String(raw))
    }
  })

  test('reads the saved choice, and keeps an off from a 0.1.x config', () => {
    assert.equal(savedUpdateChoice({ updateChoice: 'automatic' }), 'automatic')
    assert.equal(savedUpdateChoice({ updateChoice: 'ask', checkForUpdates: false }), 'ask')
    assert.equal(savedUpdateChoice({ checkForUpdates: false }), 'off')
    // 0.1.x checked by default, but that wasn't a choice to install automatically.
    assert.equal(savedUpdateChoice({ checkForUpdates: true }), null)
    assert.equal(savedUpdateChoice({}), null)
    assert.equal(savedUpdateChoice({ updateChoice: 'sometimes' }), null)
  })
})

describe('updaterBehaviour', () => {
  test('does nothing until a choice is made', () => {
    assert.deepEqual(updaterBehaviour(null, 'install'), {
      checksAutomatically: false,
      downloadsAutomatically: false,
      installsOnQuit: false,
    })
  })

  test('automatic downloads and installs on quit', () => {
    assert.deepEqual(updaterBehaviour('automatic', 'install'), {
      checksAutomatically: true,
      downloadsAutomatically: true,
      installsOnQuit: true,
    })
  })

  test('ask checks but never downloads or installs by itself', () => {
    assert.deepEqual(updaterBehaviour('ask', 'install'), {
      checksAutomatically: true,
      downloadsAutomatically: false,
      installsOnQuit: false,
    })
  })

  test('off makes no checks of its own', () => {
    assert.equal(updaterBehaviour('off', 'install').checksAutomatically, false)
    assert.equal(updaterBehaviour('off', 'install').downloadsAutomatically, false)
  })

  test('an update the user asked for installs on quit, whatever the choice', () => {
    for (const choice of ['ask', 'off', null] as const) {
      assert.equal(updaterBehaviour(choice, 'install', true).installsOnQuit, true, String(choice))
      assert.equal(updaterBehaviour(choice, 'install', true).downloadsAutomatically, false)
    }
  })

  test('a notify-only install never downloads or installs, and treats automatic as ask', () => {
    for (const choice of ['automatic', 'ask'] as const) {
      assert.deepEqual(updaterBehaviour(choice, 'notify', true), {
        checksAutomatically: true,
        downloadsAutomatically: false,
        installsOnQuit: false,
      })
    }
  })
})
