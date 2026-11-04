import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import { makeAppToken, TOKEN_ENV } from '../src/appToken.ts'

describe('makeAppToken', () => {
  test('a new, long, random token each time', () => {
    const a = makeAppToken({})
    const b = makeAppToken({})
    assert.notEqual(a, b)
    assert.ok(a.length >= 40)
    assert.match(a, /^[A-Za-z0-9_-]+$/) // safe in a cookie and a header as it is
  })

  test('the one it was started with', () => {
    const token = 'packaged-test-token-0123456789'
    assert.equal(makeAppToken({ [TOKEN_ENV]: token }), token)
  })

  test('not one too short to be a secret', () => {
    assert.notEqual(makeAppToken({ [TOKEN_ENV]: 'short' }), 'short')
    assert.notEqual(makeAppToken({ [TOKEN_ENV]: '' }), '')
  })
})
