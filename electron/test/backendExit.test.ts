import { describe, test } from 'node:test'
import * as assert from 'node:assert/strict'
import { portWasTaken, STARTUP_FAILURE } from '../src/backendExit.ts'

describe('portWasTaken', () => {
  const windows =
    "[backend:err] ERROR:    [Errno 10048] error while attempting to bind on address ('127.0.0.1', 47816): " +
    '[winerror 10048] only one usage of each socket address (protocol/network address/port) is normally permitted'
  const linux =
    "[backend:err] ERROR:    [Errno 98] error while attempting to bind on address ('127.0.0.1', 47816): address already in use"
  const macos =
    "[backend:err] ERROR:    [Errno 48] error while attempting to bind on address ('127.0.0.1', 47816): address already in use"

  for (const [os, line] of [
    ['Windows', windows],
    ['Linux', linux],
    ['macOS', macos],
  ]) {
    test(`a taken port on ${os}`, () => {
      assert.equal(portWasTaken(STARTUP_FAILURE, ['Startup complete', line]), true)
    })
  }

  test('another startup failure', () => {
    assert.equal(
      portWasTaken(STARTUP_FAILURE, ['ERROR: Traceback', 'sqlite3.OperationalError']),
      false,
    )
  })

  test('a different exit code', () => {
    assert.equal(portWasTaken(1, [linux]), false)
    assert.equal(portWasTaken(null, [linux]), false)
  })
})
