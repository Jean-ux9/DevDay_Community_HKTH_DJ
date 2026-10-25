import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import { AGENT_EXITED_CLOSE, AgentTransport } from './transport'
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
  it('a gone agent ends the connection with AGENT_EXITED_CLOSE and refuses every reconnect', () => {
    const socket = new Socket(), emit = vi.fn(), create = vi.fn(() => socket)
    const transport = new AgentTransport(create, emit)
    transport.connect('one'); socket.emit('open')
    transport.send('one', JSON.stringify({ type: 'hello' }))
    transport.agentExited('The agent exited with code 1')
    expect(socket.close).toHaveBeenCalledTimes(1)
    expect(emit).toHaveBeenLastCalledWith({ id: 'one', type: 'close', code: AGENT_EXITED_CLOSE, reason: 'The agent exited with code 1' })
    socket.emit('close', 1006, '') // the socket's own late close is not reported twice
    expect(emit.mock.calls.filter(([event]) => event.type === 'close')).toHaveLength(1)
    expect(transport.panic()).toBe(false)
    transport.connect('two')
    expect(create).toHaveBeenCalledTimes(1) // no socket to a port nobody listens on
    expect(emit).toHaveBeenLastCalledWith({ id: 'two', type: 'close', code: AGENT_EXITED_CLOSE, reason: 'The agent exited with code 1' })
    expect(transport.send('two', 'x')).toBe(false)
  })
  it('an agent that dies before the renderer connects is reported on the first connect', () => {
    const emit = vi.fn(), create = vi.fn()
    const transport = new AgentTransport(create, emit)
    transport.agentExited('The agent could not start')
    expect(emit).not.toHaveBeenCalled()
    transport.connect('first')
    expect(create).not.toHaveBeenCalled()
    expect(emit).toHaveBeenCalledWith({ id: 'first', type: 'close', code: AGENT_EXITED_CLOSE, reason: 'The agent could not start' })
  })
})
