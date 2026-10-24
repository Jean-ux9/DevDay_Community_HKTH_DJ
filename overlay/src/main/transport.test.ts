import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import { AgentTransport } from './transport'
class Socket extends EventEmitter { readyState = 1; send = vi.fn(); close = vi.fn() }
describe('main-process panic transport (fake sockets only)', () => {
  it('STOP goes on the current renderer connection without a renderer callback', () => {
    const socket = new Socket(), emit = vi.fn(), transport = new AgentTransport(() => socket, emit)
    transport.connect('one'); socket.emit('open')
    expect(emit).toHaveBeenCalledWith({ id: 'one', type: 'open' })
    expect(transport.panic()).toBe(false) // hello must remain the first frame
    transport.send('one', JSON.stringify({ type: 'hello' }))
    socket.send.mockClear()
    expect(transport.panic()).toBe(true)
    expect(JSON.parse(socket.send.mock.calls[0]![0] as string)).toMatchObject({ v: 1, type: 'stop', re: null, payload: { reason: 'hotkey' } })
  })
  it('ignores stale sockets after reconnect and cleans up current connections', () => {
    const first = new Socket(), second = new Socket(), emit = vi.fn()
    const create = vi.fn().mockReturnValueOnce(first).mockReturnValueOnce(second)
    const transport = new AgentTransport(create, emit)
    transport.connect('first'); transport.connect('second')
    first.emit('message', 'old'); first.emit('close', 1006, '')
    expect(emit).not.toHaveBeenCalled()
    second.emit('message', 'new')
    expect(emit).toHaveBeenCalledWith({ id: 'second', type: 'message', data: 'new' })
    expect(transport.send('first', 'stale')).toBe(false)
    transport.close('first'); expect(second.close).not.toHaveBeenCalled()
    transport.close(); expect(second.close).toHaveBeenCalledTimes(1)
    expect(transport.panic()).toBe(false)
  })
})
