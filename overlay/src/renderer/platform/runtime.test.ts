// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PlatformRuntime } from './runtime'
import { helloAck } from '../ws/test-utils'
import type { CursorSample, PlatformBridge, TransportEvent, WindowPolicy } from '../../shared/app'
vi.mock('../gaze/webgazer', () => ({ WebGazerProvider: class {
  onSample = vi.fn(() => () => {}); start = vi.fn(async () => {}); stop = vi.fn(); train = vi.fn()
} }))
vi.mock('../gaze/blink', () => ({ BlinkDetector: class {}, startBlinkDetection: vi.fn(async () => () => {}) }))
let runtime: PlatformRuntime
beforeEach(() => {
  vi.useFakeTimers()
  Object.defineProperty(document, 'elementsFromPoint', { value: () => [], configurable: true })
})
afterEach(() => { runtime?.dispose(); delete window.gazePlatform; vi.useRealTimers() })
const makeBridge = () => {
  let transport: (event: TransportEvent) => void = () => {}
  let hotkey: (event: 'stop' | 'toggle-source') => void = () => {}
  const cursors = new Set<(sample: CursorSample) => void>()
  const sent: { type: string; id: string; payload: Record<string, unknown> }[] = []
  let id = ''
  const bridge: PlatformBridge = {
    config: vi.fn(async () => ({ port: 12345, token: 'fake-only', camera: 'granted', gazeSource: 'mouse', debug: false } as const)),
    onCursor: cb => { cursors.add(cb); return () => { cursors.delete(cb) } },
    onHotkey: cb => { hotkey = cb; return () => {} }, onVisibility: () => () => {},
    cameraStatus: vi.fn(async () => 'granted' as const),
    windowPolicy: vi.fn(),
    onTransport: cb => { transport = cb; return () => {} },
    connect: value => { id = value; queueMicrotask(() => transport({ id, type: 'open' })) },
    send: (_id, data) => { sent.push(JSON.parse(data) as typeof sent[number]) }, close: vi.fn()
  }
  window.gazePlatform = bridge
  return { bridge, sent, hotkey: (event: 'stop' | 'toggle-source') => hotkey(event),
    cursor: (sample: CursorSample) => { for (const cb of cursors) cb(sample) },
    deliver: (message: unknown) => transport({ id, type: 'message', data: JSON.stringify(message) }) }
}
describe('platform facade with fake IPC, camera and time', () => {
  it('merges Electron camera status, keeps env mouse mode, sends no launch refresh, and disposes IPC', async () => {
    const rig = makeBridge(); runtime = new PlatformRuntime()
    await runtime.start(); await vi.advanceTimersByTimeAsync(0)
    rig.deliver(helloAck(rig.sent[0]!.id))
    expect(runtime.getSession().permissions).toEqual({ accessibility: true, screen_recording: true, camera: 'granted' })
    expect(runtime.getGaze().source).toBe('mouse')
    expect(rig.sent.map(frame => frame.type)).not.toContain('auto_refresh')
    expect(rig.bridge.cameraStatus).not.toHaveBeenCalledWith(true)
    runtime.decode(['tell'], ['JKL', 'ABC', 'TUV', 'DEF'])
    expect(rig.sent.at(-1)).toMatchObject({ type: 'decode_request', payload: { words: ['tell'], raw_keys: [['JKL', 'ABC', 'TUV', 'DEF']] } })
    runtime.dispose()
    expect(rig.bridge.close).toHaveBeenCalled()
  })
  it('uses the physical cursor for caregiver click-through even when gaze has another source', async () => {
    const rig = makeBridge(); runtime = new PlatformRuntime()
    await runtime.start(); await vi.advanceTimersByTimeAsync(0)
    const button = document.createElement('button')
    Object.defineProperty(document, 'elementsFromPoint', { value: (x: number) => x === 99 ? [button] : [], configurable: true })
    rig.cursor({ x: 99, y: 1, t: 0 })
    await vi.advanceTimersByTimeAsync(20)
    expect(rig.bridge.windowPolicy).toHaveBeenLastCalledWith({ taskActive: false, confirming: false, caregiverHover: true } satisfies WindowPolicy)
  })
  it('exposes bridge failures without starting a camera', async () => {
    delete window.gazePlatform
    runtime = new PlatformRuntime(); await runtime.start()
    expect(runtime.getSession().connection).toBe('error')
    expect(runtime.getSession().lastError?.code).toBe('platform_unavailable')
  })
})
