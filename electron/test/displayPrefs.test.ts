import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import {
  isDisplayPref,
  sanitizeDisplayPrefs,
  sanitizeWindowColors,
  themeSourceFor,
  withDisplayPref,
} from '../src/displayPrefs.ts'

describe('sanitizeDisplayPrefs', () => {
  test('keeps the UI display choices', () => {
    const prefs = {
      'scene-atlas-theme': 'dark',
      'scene-atlas-palette': 'lapis',
      'scene-atlas-text-size': 'larger',
    }
    assert.deepEqual(sanitizeDisplayPrefs(prefs), prefs)
  })

  test('drops anything that is not a short token under a scene-atlas- key', () => {
    assert.deepEqual(
      sanitizeDisplayPrefs({
        'scene-atlas-theme': 'dark',
        'other-key': 'dark',
        'scene-atlas-palette': '<script>',
        'scene-atlas-contrast': 7,
        'scene-atlas-text-size': 'x'.repeat(33),
      }),
      { 'scene-atlas-theme': 'dark' },
    )
  })

  test('treats a missing or malformed section as empty', () => {
    for (const raw of [undefined, null, 'dark', ['a'], 3]) {
      assert.deepEqual(sanitizeDisplayPrefs(raw), {})
    }
  })

  test('caps the number of entries', () => {
    const many = Object.fromEntries(
      Array.from({ length: 50 }, (_, i) => [`scene-atlas-k${i}`, 'v']),
    )
    assert.equal(Object.keys(sanitizeDisplayPrefs(many)).length, 32)
  })
})

describe('withDisplayPref', () => {
  test('sets or replaces a value without mutating', () => {
    const prefs = { 'scene-atlas-theme': 'dark' }
    assert.deepEqual(withDisplayPref(prefs, 'scene-atlas-theme', 'light'), {
      'scene-atlas-theme': 'light',
    })
    assert.deepEqual(prefs, { 'scene-atlas-theme': 'dark' })
  })

  test('does not grow past the cap, but can still replace', () => {
    const full = Object.fromEntries(
      Array.from({ length: 32 }, (_, i) => [`scene-atlas-k${i}`, 'v']),
    )
    assert.equal(withDisplayPref(full, 'scene-atlas-new', 'v'), full)
    assert.equal(withDisplayPref(full, 'scene-atlas-k0', 'w')['scene-atlas-k0'], 'w')
  })
})

describe('isDisplayPref', () => {
  test('validates a single entry from the renderer', () => {
    assert.equal(isDisplayPref('scene-atlas-palette', 'sienna'), true)
    assert.equal(isDisplayPref('scene-atlas-palette', 'Sienna'), false)
    assert.equal(isDisplayPref('__proto__', 'x'), false)
  })
})

describe('sanitizeWindowColors', () => {
  test('accepts two hex colours, lower-cased', () => {
    assert.deepEqual(sanitizeWindowColors({ background: '#0E1118', foreground: '#ede8dc' }), {
      background: '#0e1118',
      foreground: '#ede8dc',
    })
  })

  test('rejects anything else', () => {
    for (const raw of [
      null,
      { background: 'red', foreground: '#ffffff' },
      { background: '#fff', foreground: '#ffffff' },
      { background: '#000000' },
      { background: '#000000; x', foreground: '#ffffff' },
    ]) {
      assert.equal(sanitizeWindowColors(raw), null)
    }
  })
})

describe('themeSourceFor', () => {
  test('follows an explicit theme, otherwise the system', () => {
    assert.equal(themeSourceFor({ 'scene-atlas-theme': 'light' }), 'light')
    assert.equal(themeSourceFor({ 'scene-atlas-theme': 'dark' }), 'dark')
    assert.equal(themeSourceFor({ 'scene-atlas-theme': 'system' }), 'system')
    assert.equal(themeSourceFor({}), 'system')
  })
})
