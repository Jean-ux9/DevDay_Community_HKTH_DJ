// Webcam gaze from MediaPipe Face Landmarker: iris position inside each eye + head pose, mapped to
// screen pixels by a ridge regression trained on calibration dots (the approach of EyeTrax and
// similar trackers). Pure math, no camera: unit-testable with synthetic landmarks.
import type { Landmark } from './blink'

/** Eye corners and iris centres in the 478-point Face Landmarker mesh. */
const EYES = [
  { outer: 33, inner: 133, top: 159, bottom: 145 },
  { outer: 263, inner: 362, top: 386, bottom: 374 }
] as const
const IRIS_CENTRES = [468, 473] as const

const sub = (a: Landmark, b: Landmark) => ({ x: a.x - b.x, y: a.y - b.y })
const mid = (a: Landmark, b: Landmark) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })

/** Iris position along (u) and across (v) the eye's corner-to-corner axis, in eye widths. */
function irisInEye(iris: Landmark, outer: Landmark, inner: Landmark): [number, number] {
  const axis = sub(inner, outer)
  const len2 = Math.max(axis.x ** 2 + axis.y ** 2, 1e-9)
  const d = sub(iris, outer)
  return [(d.x * axis.x + d.y * axis.y) / len2, (axis.x * d.y - axis.y * d.x) / len2]
}

/** Eye openness (lid gap / eye width); low means a blink. */
export function eyeOpenness(points: readonly Landmark[]): number {
  let total = 0
  for (const eye of EYES) {
    const [o, i, t, b] = [points[eye.outer], points[eye.inner], points[eye.top], points[eye.bottom]]
    if (!o || !i || !t || !b) return 0
    total += Math.hypot(t.x - b.x, t.y - b.y) / Math.max(Math.hypot(i.x - o.x, i.y - o.y), 1e-9)
  }
  return total / EYES.length
}

/**
 * MediaPipe's learned per-eye gaze scores (0..1). Vertical gaze barely moves the iris in the image,
 * so these carry most of the up/down signal.
 */
export const GAZE_BLENDSHAPES = ['eyeLookUpLeft', 'eyeLookDownLeft', 'eyeLookInLeft', 'eyeLookOutLeft',
  'eyeLookUpRight', 'eyeLookDownRight', 'eyeLookInRight', 'eyeLookOutRight'] as const
export type Blendshapes = Partial<Record<string, number>>

/**
 * Feature vector for one frame, or null without irises. `matrix` is the 4×4 column-major facial
 * transformation matrix (head pose); without it head pose falls back to the face's image position.
 * `blendshapes` adds MediaPipe's gaze scores (missing ones count as 0).
 */
export function gazeFeatures(points: readonly Landmark[], matrix?: ArrayLike<number> | null,
  blendshapes?: Blendshapes | null): number[] | null {
  const irises = IRIS_CENTRES.map(index => points[index])
  if (irises.some(p => !p)) return null
  const eyes: number[] = []
  const lids: number[] = []
  for (const eye of EYES) {
    const outer = points[eye.outer], inner = points[eye.inner]
    if (!outer || !inner) return null
    // Pair each eye with the nearer iris, so the mesh's left/right convention can't swap them.
    const centre = mid(outer, inner)
    const iris = irises.reduce((a, b) => Math.hypot(a!.x - centre.x, a!.y - centre.y) <= Math.hypot(b!.x - centre.x, b!.y - centre.y) ? a : b)!
    eyes.push(...irisInEye(iris, outer, inner))
    // Iris between the lids (0 = upper lid, 1 = lower): moves more than the iris itself looking up/down.
    const top = points[eye.top], bottom = points[eye.bottom]
    lids.push(top && bottom ? (iris.y - top.y) / Math.max(Math.abs(bottom.y - top.y), 1e-6) : 0.5)
  }
  const u = (eyes[0]! + eyes[2]!) / 2, v = (eyes[1]! + eyes[3]!) / 2
  const nose = points[1] ?? mid(points[33]!, points[263]!)
  const pose = matrix && matrix.length >= 16
    ? [matrix[8]!, matrix[9]!, matrix[12]!, matrix[13]!, matrix[14]!]
    : [nose.x, nose.y, 0, 0, Math.hypot(points[33]!.x - points[263]!.x, points[33]!.y - points[263]!.y)]
  const shapes = GAZE_BLENDSHAPES.map(name => blendshapes?.[name] ?? 0)
  const up = (shapes[0]! + shapes[4]!) / 2 - (shapes[1]! + shapes[5]!) / 2
  return [...eyes, u * u, v * v, u * v, ...lids, eyeOpenness(points), ...shapes, up, up * up, ...pose]
}

/** Solves A·x = b in place (Gaussian elimination with partial pivoting). */
function solve(a: number[][], b: number[]): number[] {
  const n = b.length
  for (let col = 0; col < n; col++) {
    let pivot = col
    for (let row = col + 1; row < n; row++) if (Math.abs(a[row]![col]!) > Math.abs(a[pivot]![col]!)) pivot = row
    ;[a[col], a[pivot]] = [a[pivot]!, a[col]!]
    ;[b[col], b[pivot]] = [b[pivot]!, b[col]!]
    const p = a[col]![col]! || 1e-12
    for (let row = col + 1; row < n; row++) {
      const f = a[row]![col]! / p
      for (let k = col; k < n; k++) a[row]![k]! -= f * a[col]![k]!
      b[row]! -= f * b[col]!
    }
  }
  const x = new Array<number>(n).fill(0)
  for (let row = n - 1; row >= 0; row--) {
    let s = b[row]!
    for (let k = row + 1; k < n; k++) s -= a[row]![k]! * x[k]!
    x[row] = s / (a[row]![row]! || 1e-12)
  }
  return x
}

/** Ridge regression features → (x, y), on standardized features. Refit after every new sample. */
export class GazeRegression {
  private readonly samples: { f: number[]; x: number; y: number }[] = []
  private model: { mean: number[]; std: number[]; wx: number[]; wy: number[] } | null = null
  constructor(private readonly lambda = 1, private readonly maxSamples = 1500) {}

  get size(): number { return this.samples.length }
  get trained(): boolean { return this.model !== null }

  add(features: readonly number[], x: number, y: number): void {
    this.samples.push({ f: [...features], x, y })
    if (this.samples.length > this.maxSamples) this.samples.shift()
    this.fit()
  }

  clear(): void { this.samples.length = 0; this.model = null }

  predict(features: readonly number[]): { x: number; y: number } | null {
    const m = this.model
    if (!m) return null
    const z = [1, ...features.map((v, i) => (v - m.mean[i]!) / m.std[i]!)]
    let x = 0, y = 0
    for (let i = 0; i < z.length; i++) { x += z[i]! * m.wx[i]!; y += z[i]! * m.wy[i]! }
    return { x, y }
  }

  private fit(): void {
    // Too few distinct targets would extrapolate wildly: wait for a few calibration dots.
    const targets = new Set(this.samples.map(s => `${Math.round(s.x / 40)},${Math.round(s.y / 40)}`))
    if (this.samples.length < 10 || targets.size < 3) { this.model = null; return }
    const dim = this.samples[0]!.f.length
    const mean = new Array<number>(dim).fill(0), std = new Array<number>(dim).fill(0)
    for (const s of this.samples) s.f.forEach((v, i) => { mean[i]! += v / this.samples.length })
    for (const s of this.samples) s.f.forEach((v, i) => { std[i]! += (v - mean[i]!) ** 2 / this.samples.length })
    for (let i = 0; i < dim; i++) std[i] = Math.sqrt(std[i]!) || 1
    const n = dim + 1
    const ata = Array.from({ length: n }, () => new Array<number>(n).fill(0))
    const atx = new Array<number>(n).fill(0), aty = new Array<number>(n).fill(0)
    for (const s of this.samples) {
      const z = [1, ...s.f.map((v, i) => (v - mean[i]!) / std[i]!)]
      for (let i = 0; i < n; i++) {
        atx[i]! += z[i]! * s.x
        aty[i]! += z[i]! * s.y
        for (let j = 0; j < n; j++) ata[i]![j]! += z[i]! * z[j]!
      }
    }
    for (let i = 1; i < n; i++) ata[i]![i]! += this.lambda // no penalty on the intercept
    const wx = solve(ata.map(r => [...r]), atx), wy = solve(ata.map(r => [...r]), aty)
    this.model = { mean, std, wx, wy }
  }
}
