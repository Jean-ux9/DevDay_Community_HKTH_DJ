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
