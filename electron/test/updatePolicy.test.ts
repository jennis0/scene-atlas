import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import {
  canCheck,
  parseFeedOverride,
  releasePageUrl,
  updateModeFor,
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
  })

  test('falls back to the releases list for anything that is not a version', () => {
    for (const version of [undefined, '', '1.0', '1.0.0/../../evil', '1.0.0?x=1']) {
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
