import { describe, expect, it } from 'vitest'
import type { Landmark } from './blink'
import { GazeRegression, eyeOpenness, gazeFeatures } from './iris'
import { BLINK_OPENNESS, MediaPipeGazeProvider, type FaceFrame } from './mediapipe'

/** A synthetic face: eyes at fixed corners; irises shifted by (gx, gy) in eye widths; eyes open or shut. */
function face(gx: number, gy: number, open = true): Landmark[] {
  const p: Landmark[] = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }))
  const eye = (outer: number, inner: number, top: number, bottom: number, iris: number, x0: number, x1: number) => {
    p[outer] = { x: x0, y: 0.4 }; p[inner] = { x: x1, y: 0.4 }
    const gap = open ? 0.02 : 0.001
    p[top] = { x: (x0 + x1) / 2, y: 0.4 - gap }; p[bottom] = { x: (x0 + x1) / 2, y: 0.4 + gap }
    const w = x1 - x0
    p[iris] = { x: x0 + w * (0.5 + gx), y: 0.4 + Math.abs(w) * gy }
  }
  eye(33, 133, 159, 145, 468, 0.35, 0.45)
  eye(263, 362, 386, 374, 473, 0.65, 0.55)
  p[1] = { x: 0.5, y: 0.5 }
  return p
}

describe('gaze features', () => {
  it('track iris position inside each eye', () => {
    const left = gazeFeatures(face(-0.1, 0))!, right = gazeFeatures(face(0.1, 0))!
    expect(left[0]).toBeLessThan(right[0]!)
    expect(gazeFeatures(face(0, 0.1))![1]).toBeGreaterThan(gazeFeatures(face(0, -0.1))![1]!)
  })
  it('need both irises', () => {
    const p = face(0, 0); delete (p as Partial<Landmark>[])[473]
    expect(gazeFeatures(p)).toBeNull()
  })
  it('tell open eyes from a blink', () => {
    expect(eyeOpenness(face(0, 0))).toBeGreaterThan(BLINK_OPENNESS)
    expect(eyeOpenness(face(0, 0, false))).toBeLessThan(BLINK_OPENNESS)
  })
})

describe('gaze regression', () => {
  const screenOf = (gx: number, gy: number) => ({ x: 720 + gx * 6000, y: 450 + gy * 4000 })
  const grid = [-0.1, 0, 0.1]

  it('predicts nothing until a few calibration dots are in', () => {
    const r = new GazeRegression()
    for (let i = 0; i < 20; i++) r.add(gazeFeatures(face(0, 0))!, 720, 450)
    expect(r.trained).toBe(false)
  })

  it('learns the iris → screen mapping from 9 dots and generalizes between them', () => {
    const r = new GazeRegression(0.01)
    for (const gx of grid) for (const gy of grid) for (let k = 0; k < 12; k++) {
      const noise = (k % 3 - 1) * 0.002
      r.add(gazeFeatures(face(gx + noise, gy - noise))!, screenOf(gx, gy).x, screenOf(gx, gy).y)
    }
    const p = r.predict(gazeFeatures(face(0.05, -0.05))!)!
    const want = screenOf(0.05, -0.05)
    expect(Math.hypot(p.x - want.x, p.y - want.y)).toBeLessThan(80)
  })
})

describe('MediaPipe gaze provider (fake tracker, no camera)', () => {
  const rig = () => {
    let next: FaceFrame | null | undefined = { landmarks: face(0, 0), matrix: null }
    const provider = new MediaPipeGazeProvider(new GazeRegression(0.01), async () => ({ detect: () => next, close: () => {} }))
    const samples: { x: number; y: number; confidence: number }[] = []
    provider.onSample(s => samples.push(s))
    return { provider, samples, show: (f: FaceFrame | null | undefined) => { next = f } }
  }

  it('reports no gaze before training, without a face, and while blinking', async () => {
    const { provider, samples, show } = rig()
    await provider.start()
    provider.frame(1)
    show(null); provider.frame(2)
    show({ landmarks: face(0, 0, false), matrix: null }); provider.frame(3)
    show(undefined); provider.frame(4) // no new camera frame: nothing emitted
    expect(samples.map(s => s.confidence)).toEqual([0, 0, 0])
    provider.stop()
  })

  it('trains on the dots it is shown and then follows the eyes', async () => {
    const { provider, samples, show } = rig()
    await provider.start()
    const dots: [number, number, number, number][] = []
    for (const gx of [-0.1, 0, 0.1]) for (const gy of [-0.1, 0, 0.1]) dots.push([gx, gy, 720 + gx * 6000, 450 + gy * 4000])
    for (const [gx, gy, x, y] of dots) for (let k = 0; k < 10; k++) {
      show({ landmarks: face(gx + (k % 2) * 0.001, gy), matrix: null }); provider.frame(k); provider.train(x, y)
    }
    expect(provider.trained).toBe(true)
    show({ landmarks: face(0.1, 0.1), matrix: null }); provider.frame(100)
    const last = samples.at(-1)!
    expect(last.confidence).toBe(1)
    expect(Math.hypot(last.x - 1320, last.y - 850)).toBeLessThan(60)
    provider.stop()
  })
})

describe('gaze regression with a moving head', () => {
  // Head pose as the 4×4 column-major matrix: yaw-ish (m8), pitch-ish (m9), translation (m12, m13, m14).
  const pose = (yaw: number, pitch: number) => {
    const m = new Array<number>(16).fill(0)
    m[0] = m[5] = m[10] = m[15] = 1
    m[8] = yaw; m[9] = pitch; m[14] = -50
    return m
  }
  // Where you look depends on both the eyes and the head direction.
  const target = (gx: number, gy: number, yaw: number, pitch: number) => ({ x: 720 + gx * 6000 + yaw * 2500, y: 450 + gy * 4000 + pitch * 2000 })

  it('trained over 3 head-pose rounds, it still finds the gaze for an unseen head pose', () => {
    const r = new GazeRegression(0.01)
    const grid = [-0.1, -0.05, 0, 0.05, 0.1]
    for (const [yaw, pitch] of [[0, 0], [-0.1, 0], [0.1, 0], [0, -0.1], [0, 0.1]] as const)
      for (const gx of grid) for (const gy of grid) {
        const t = target(gx, gy, yaw, pitch)
        r.add(gazeFeatures(face(gx, gy), pose(yaw, pitch))!, t.x, t.y)
      }
    const want = target(0.03, -0.04, 0.06, -0.05)
    const got = r.predict(gazeFeatures(face(0.03, -0.04), pose(0.06, -0.05))!)!
    expect(Math.hypot(got.x - want.x, got.y - want.y)).toBeLessThan(60)
  })

  it('a model trained with the head still mispredicts once the head turns (why the rounds exist)', () => {
    const r = new GazeRegression(0.01)
    for (const gx of [-0.1, 0, 0.1]) for (const gy of [-0.1, 0, 0.1]) for (let k = 0; k < 3; k++) {
      const t = target(gx, gy, 0, 0)
      r.add(gazeFeatures(face(gx + k * 0.001, gy), pose(0, 0))!, t.x, t.y)
    }
    const want = target(0, 0, 0.1, 0)
    const got = r.predict(gazeFeatures(face(0, 0), pose(0.1, 0))!)!
    expect(Math.hypot(got.x - want.x, got.y - want.y)).toBeGreaterThan(100)
  })
})
