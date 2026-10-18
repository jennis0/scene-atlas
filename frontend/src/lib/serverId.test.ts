import { describe, expect, it } from 'vitest'
import { serverId } from './serverId'

describe('serverId', () => {
  it('reads a server id, and gives null for a key created locally', () => {
    expect(serverId('42')).toBe(42)
    expect(serverId('3f2b9c1e-8d4a-4f6b-9a7e-2c5d8e1f0a3b')).toBeNull()
    expect(serverId('')).toBeNull()
  })
})
