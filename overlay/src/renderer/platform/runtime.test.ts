// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PlatformRuntime } from './runtime'
import { dwellStore } from '../dwell/context'
import { helloAck } from '../ws/test-utils'
import type { CursorSample, PlatformBridge, TransportEvent, WindowPolicy } from '../../shared/app'
vi.mock('../gaze/mediapipe', () => ({ MediaPipeGazeProvider: class {
  onSample = vi.fn(() => () => {}); start = vi.fn(async () => {}); stop = vi.fn(); train = vi.fn()
  startRecording = vi.fn(); takeRecording = vi.fn(() => [])
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
  let hotkey: (event: 'stop' | 'toggle-source' | 'toggle-click') => void = () => {}
  const cursors = new Set<(sample: CursorSample) => void>()
  const sent: { type: string; id: string; payload: Record<string, unknown> }[] = []
  let id = ''
  const bridge: PlatformBridge = {
    config: vi.fn(async () => ({ port: 12345, token: 'fake-only', camera: 'granted', gazeSource: 'mouse', debug: false } as const)),
    onCursor: cb => { cursors.add(cb); return () => { cursors.delete(cb) } },
    onHotkey: cb => { hotkey = cb; return () => {} }, onVisibility: () => () => {},
    cameraStatus: vi.fn(async () => 'granted' as const),
    windowPolicy: vi.fn(), quit: vi.fn(), saveDebug: vi.fn(async () => null),
    onTransport: cb => { transport = cb; return () => {} },
    connect: value => { id = value; queueMicrotask(() => transport({ id, type: 'open' })) },
    send: (_id, data) => { sent.push(JSON.parse(data) as typeof sent[number]) }, close: vi.fn()
  }
  window.gazePlatform = bridge
  return { bridge, sent, hotkey: (event: 'stop' | 'toggle-source' | 'toggle-click') => hotkey(event),
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
  it('⌃⌥⌘D toggles click mode: dwell off except STOP, real clicks on', async () => {
    const rig = makeBridge(); runtime = new PlatformRuntime()
    await runtime.start(); await vi.advanceTimersByTimeAsync(0)
    expect(runtime.getGaze().clickMode).toBe(false)
    rig.hotkey('toggle-click')
    expect(runtime.getGaze().clickMode).toBe(true)
    expect(dwellStore.options.clickMode).toBe(true)
    rig.hotkey('toggle-click')
    expect(runtime.getGaze().clickMode).toBe(false)
    expect(dwellStore.options.clickMode).toBe(false)
  })
  it('completed dwells train the camera tracker, but not with magnetic targets on (head pointer mode)', async () => {
    makeBridge(); runtime = new PlatformRuntime()
    await runtime.start(); await vi.advanceTimersByTimeAsync(0)
    await runtime.startCalibration()
    const provider = (runtime as unknown as { provider: { train: ReturnType<typeof vi.fn> } }).provider
    const select = () => {
      const off = dwellStore.manager.register({ id: 'p', rect: { x: 0, y: 0, w: 160, h: 120 }, dwellMs: 800, variant: 'card' })
      for (let t = 0; t <= 1000; t += 10) dwellStore.manager.update({ x: 80, y: 60, t: 10_000 + t })
      off(); dwellStore.manager.loseGaze()
    }
    select()
    expect(provider.train).toHaveBeenCalledTimes(1)
    runtime.setHeadPointer(true)
    await vi.advanceTimersByTimeAsync(700) // past the select cooldown
    select()
    expect(provider.train).toHaveBeenCalledTimes(1)
  })
  it('exports the last calibration to the debug folder: training dots, check dots and frames', async () => {
    const rig = makeBridge(); runtime = new PlatformRuntime()
    const saveDebug = vi.fn(async (name: string, _json: string) => `/repo/.debug/${name}`)
    rig.bridge.saveDebug = saveDebug
    await runtime.start(); await vi.advanceTimersByTimeAsync(0)
    await runtime.startCalibration('webgazer')
    runtime.train(100, 200)
    const path = await runtime.exportCalibration({ result: { meanErrorPx: 50 } })
    expect(path).toMatch(/\.debug\/calibration-webgazer-\d{4}-\d{2}-\d{2}-[\d-]+\.json$/)
    const data = JSON.parse(saveDebug.mock.calls[0]![1])
    expect(data).toMatchObject({ target: 'webgazer', trains: [{ x: 100, y: 200 }], result: { meanErrorPx: 50 }, frames: [] })
    expect(await runtime.exportCalibration()).toBeNull() // one export per calibration
  })
  it('drift: on-target selections nudge the camera offset toward the centre; magnet-held ones do not', async () => {
    makeBridge(); runtime = new PlatformRuntime()
    await runtime.start(); await vi.advanceTimersByTimeAsync(0)
    await runtime.startCalibration()
    const r = runtime as unknown as { sample(s: { x: number; y: number; t: number; confidence: number }): void; offset: { x: number; y: number } }
    const selectAt = (x: number, y: number) => {
      r.sample({ x, y, t: 0, confidence: 1 })
      const off = dwellStore.manager.register({ id: 'd', rect: { x: 0, y: 0, w: 160, h: 120 }, dwellMs: 800, variant: 'card' })
      dwellStore.manager.setMagnet(200)
      for (let t = 0; t <= 1000; t += 10) dwellStore.manager.update({ x, y, t: 50_000 + t })
      off(); dwellStore.manager.loseGaze(); dwellStore.manager.setMagnet(0)
    }
    selectAt(120, 60) // on the card, 40 px right of its centre
    expect(r.offset.x).toBeCloseTo(-12) // 0.3 × (80 − 120)
    expect(r.offset.y).toBeCloseTo(0)
    await vi.advanceTimersByTimeAsync(700)
    selectAt(250, 60) // held by the magnet from outside: no correction
    expect(r.offset.x).toBeCloseTo(-12)
  })
  it('recenter averages raw samples after the settle time into the offset', async () => {
    makeBridge(); runtime = new PlatformRuntime()
    await runtime.start(); await vi.advanceTimersByTimeAsync(0)
    await runtime.startCalibration()
    const r = runtime as unknown as { sample(s: { x: number; y: number; t: number; confidence: number }): void }
    const done = runtime.recenter(700, 450, 200, 300)
    r.sample({ x: 0, y: 0, t: 0, confidence: 1 }) // during the settle time: ignored
    await vi.advanceTimersByTimeAsync(250)
    r.sample({ x: 650, y: 500, t: 0, confidence: 1 }); r.sample({ x: 670, y: 480, t: 0, confidence: 1 })
    await vi.advanceTimersByTimeAsync(300)
    expect(await done).toEqual({ x: 40, y: -40 })
  })
  it('exposes bridge failures without starting a camera', async () => {
    delete window.gazePlatform
    runtime = new PlatformRuntime(); await runtime.start()
    expect(runtime.getSession().connection).toBe('error')
    expect(runtime.getSession().lastError?.code).toBe('platform_unavailable')
  })
})
