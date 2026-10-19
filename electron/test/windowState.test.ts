import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import { restoredBounds, sanitizeWindowState, type WindowState } from '../src/windowState.ts'

const LAPTOP = { x: 0, y: 0, width: 1366, height: 728 }
const PRIMARY = { x: 0, y: 0, width: 2560, height: 1400 }
const SECOND = { x: 2560, y: 0, width: 1920, height: 1040 }

function saved(overrides: Partial<WindowState> = {}): WindowState {
  return { x: 100, y: 80, width: 1600, height: 1000, maximized: false, ...overrides }
}

describe('sanitizeWindowState', () => {
  test('keeps a well-formed state', () => {
    assert.deepEqual(sanitizeWindowState(saved({ maximized: true })), saved({ maximized: true }))
  })

  test('accepts positions left of or above the primary screen', () => {
    assert.deepEqual(sanitizeWindowState(saved({ x: -1800, y: -40 })), saved({ x: -1800, y: -40 }))
  })

  test('drops anything malformed', () => {
    for (const raw of [
      undefined,
      null,
      'big',
      [1, 2],
      { ...saved(), width: 0 },
      { ...saved(), height: -5 },
      { ...saved(), x: 1.5 },
      { ...saved(), y: '80' },
      { ...saved(), maximized: 'yes' },
      { x: 1, y: 1, width: 900 },
    ]) {
      assert.equal(sanitizeWindowState(raw), null, JSON.stringify(raw))
    }
  })
})

describe('restoredBounds', () => {
  test('opens at the default size, centred, the first time', () => {
    assert.deepEqual(restoredBounds(null, [PRIMARY]), { width: 1400, height: 900 })
  })

  test('fits the default size to a small screen', () => {
    assert.deepEqual(restoredBounds(null, [LAPTOP]), { width: 1366, height: 728 })
  })

  test('reopens where it was', () => {
    assert.deepEqual(restoredBounds(saved(), [PRIMARY]), {
      x: 100,
      y: 80,
      width: 1600,
      height: 1000,
    })
  })

  test('reopens on a second screen that is still there', () => {
    assert.deepEqual(restoredBounds(saved({ x: 2700, y: 50 }), [PRIMARY, SECOND]), {
      x: 2700,
      y: 50,
      width: 1600,
      height: 1000,
    })
  })

  test('is placed by the OS when its screen has gone', () => {
    assert.deepEqual(restoredBounds(saved({ x: 2700, y: 50 }), [PRIMARY]), {
      width: 1600,
      height: 1000,
    })
  })

  test('keeps the position while enough of the top edge is on screen to grab', () => {
    // 150 px of the top edge still on the primary screen
    assert.equal(restoredBounds(saved({ x: 2410 }), [PRIMARY]).x, 2410)
    // Only 50 px: not enough
    assert.equal(restoredBounds(saved({ x: 2510 }), [PRIMARY]).x, undefined)
    // Top edge above every screen
    assert.equal(restoredBounds(saved({ y: -200 }), [PRIMARY]).y, undefined)
  })

  test('shrinks to fit the screen and never below the minimum', () => {
    assert.deepEqual(restoredBounds(saved({ x: 0, y: 0, width: 3000, height: 2000 }), [LAPTOP]), {
      x: 0,
      y: 0,
      width: 1366,
      height: 728,
    })
    assert.deepEqual(restoredBounds(saved({ width: 400, height: 300 }), [PRIMARY]), {
      x: 100,
      y: 80,
      width: 900,
      height: 600,
    })
  })

  test('keeps the saved size if no screen is reported', () => {
    assert.deepEqual(restoredBounds(saved(), []), { width: 1600, height: 1000 })
  })
})
