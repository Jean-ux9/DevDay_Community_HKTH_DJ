import { describe, expect, it } from 'vitest'
import type { Landmark } from './blink'
import { HeadPoseProvider, headAngles } from './headpose'
import type { FaceFrame } from './mediapipe'

/** Column-major 4×4 pose whose forward axis points at (yaw, pitch). */
const pose = (yaw: number, pitch: number): number[] => {
  const m = new Array<number>(16).fill(0)
  m[0] = m[5] = m[15] = 1
  m[8] = Math.sin(yaw) * Math.cos(pitch); m[9] = Math.sin(pitch); m[10] = Math.cos(yaw) * Math.cos(pitch)
  return m
}
const closedEyes: Landmark[] = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }))

describe('head angles', () => {
  it('reads yaw and pitch from the transformation matrix', () => {
    const [yaw, pitch] = headAngles(pose(0.2, -0.1))!
    expect(yaw).toBeCloseTo(0.2, 6)
    expect(pitch).toBeCloseTo(-0.1, 6)
    expect(headAngles(null)).toBeNull()
  })
})

describe('head pose provider (fake tracker, no camera)', () => {
  // A small, comfortable head turn (±0.12 rad ≈ ±7°) should reach the whole screen.
  const screen = (yaw: number, pitch: number) => ({ x: 720 + yaw * 5500, y: 450 - pitch * 3500 })

  it('maps small head turns to the whole screen after a 9-dot calibration, and ignores blinks', async () => {
    let next: FaceFrame | undefined
    const provider = new HeadPoseProvider(async () => ({ detect: () => next, close: () => {} }))
    const out: { x: number; y: number; confidence: number }[] = []
    provider.onSample(s => out.push(s))
    await provider.start()
    for (const yaw of [-0.12, 0, 0.12]) for (const pitch of [-0.12, 0, 0.12]) for (let k = 0; k < 8; k++) {
      const jitter = (k % 3 - 1) * 0.003
      next = { landmarks: closedEyes, matrix: pose(yaw + jitter, pitch - jitter) }
      provider.frame(k)
      const t = screen(yaw, pitch)
      provider.train(t.x, t.y)
    }
    // Eyes closed on purpose: head pointing keeps working through blinks.
    next = { landmarks: closedEyes, matrix: pose(0.1, 0.1) }
    provider.frame(100)
    const last = out.at(-1)!
    expect(last.confidence).toBe(1)
    const want = screen(0.1, 0.1)
    expect(Math.hypot(last.x - want.x, last.y - want.y)).toBeLessThan(25)
    provider.stop()
  })
})

describe('head features', () => {
  it('use the nose tip as well, so a noisy pose matrix still maps well', async () => {
    const noisy = (yaw: number, pitch: number, k: number) => pose(yaw + ((k * 7919) % 11 - 5) * 0.004, pitch - ((k * 104729) % 11 - 5) * 0.004)
    const nose = (yaw: number, pitch: number): Landmark[] => {
      const lm = closedEyes.map(p => ({ ...p }))
      lm[1] = { x: 0.5 + yaw * 0.9, y: 0.5 - pitch * 0.9 } // the nose tip moves smoothly with the head
      return lm
    }
    const screen = (yaw: number, pitch: number) => ({ x: 720 + yaw * 5500, y: 450 - pitch * 3500 })
    let next: FaceFrame | undefined
    const provider = new HeadPoseProvider(async () => ({ detect: () => next, close: () => {} }))
    const out: { x: number; y: number }[] = []
    provider.onSample(s => out.push(s))
    await provider.start()
    let k = 0
    for (const yaw of [-0.12, -0.06, 0, 0.06, 0.12]) for (const pitch of [-0.12, -0.04, 0.04, 0.12]) for (let i = 0; i < 10; i++) {
      next = { landmarks: nose(yaw, pitch), matrix: noisy(yaw, pitch, k++) }
      provider.frame(k)
      const t = screen(yaw, pitch)
      provider.train(t.x, t.y)
    }
    next = { landmarks: nose(0.09, -0.08), matrix: noisy(0.09, -0.08, 3) }
    provider.frame(1000)
    const want = screen(0.09, -0.08), got = out.at(-1)!
    expect(Math.hypot(got.x - want.x, got.y - want.y)).toBeLessThan(40)
  })
})

describe('calibration recording', () => {
  it('keeps compact raw signals per frame while recording, and nothing otherwise', async () => {
    let next: FaceFrame | null | undefined = { landmarks: closedEyes, matrix: pose(0.1, 0) }
    const provider = new HeadPoseProvider(async () => ({ detect: () => next, close: () => {} }))
    await provider.start()
    provider.frame(1)
    provider.startRecording()
    provider.frame(2)
    next = null; provider.frame(3)
    const frames = provider.takeRecording()
    expect(frames).toHaveLength(2)
    expect(frames[0]).toMatchObject({ t: 2, face: true })
    expect(frames[0]!.matrix).toHaveLength(16)
    expect(frames[0]!.landmarks![1]).toEqual([0.5, 0.5, 0])
    expect(frames[1]).toEqual({ t: 3, face: false })
    provider.frame(4)
    expect(provider.takeRecording()).toEqual([])
  })
})
