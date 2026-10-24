import type { GazeSample } from './GazeProvider'
export interface CalibrationState { validating: boolean; validationPoint: { x: number; y: number } | null; pointIndex: number; error: string | null }
/** Validation never trains the regression. Each displayed dot gets fresh held-out samples. */
/** meanErrorPx: raw distance to the dots. X/Y split it by axis; offsetPx is the steady part (bias), the rest is jitter. */
export interface ValidationResult { meanErrorPx: number; meanXPx?: number; meanYPx?: number; offsetPx?: number }
export class CalibrationController {
  private state: CalibrationState = { validating: false, validationPoint: null, pointIndex: 0, error: null }
  private readonly listeners = new Set<() => void>()
  private capture: ((sample: GazeSample) => void) | null = null
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  getSnapshot = (): CalibrationState => this.state
  private set(patch: Partial<CalibrationState>): void { this.state = { ...this.state, ...patch }; for (const listener of this.listeners) listener() }
  sample(sample: GazeSample): void { this.capture?.(sample) }
  /** Each dot is shown settleMs + measureMs; only samples after settleMs count. */
  async validate(points: { x: number; y: number }[], { settleMs = 400, measureMs = 800 }: { settleMs?: number; measureMs?: number } = {}): Promise<ValidationResult> {
    if (this.state.validating) throw new Error('Validation already running')
    if (!points.length || points.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y))) throw new Error('Validation needs finite dot positions')
    this.set({ validating: true, error: null })
    const errors: number[] = [], xs: number[] = [], ys: number[] = [], offsets: number[] = []
    try {
      for (const [pointIndex, point] of points.entries()) {
        this.set({ validationPoint: point, pointIndex })
        const start = performance.now()
        const samples: { dx: number; dy: number }[] = []
        this.capture = sample => {
          if (sample.t - start >= settleMs && sample.confidence > 0) samples.push({ dx: sample.x - point.x, dy: sample.y - point.y })
        }
        await new Promise<void>(resolve => setTimeout(resolve, settleMs + measureMs))
        this.capture = null
        if (!samples.length) throw new Error('No gaze samples during validation; check camera/face tracking')
        const mean = (f: (s: { dx: number; dy: number }) => number) => samples.reduce((sum, s) => sum + f(s), 0) / samples.length
        errors.push(mean(s => Math.hypot(s.dx, s.dy)))
        xs.push(mean(s => Math.abs(s.dx)))
        ys.push(mean(s => Math.abs(s.dy)))
        offsets.push(Math.hypot(mean(s => s.dx), mean(s => s.dy))) // steady offset, without the jitter
      }
      const avg = (v: number[]) => v.reduce((sum, e) => sum + e, 0) / v.length
      return { meanErrorPx: avg(errors), meanXPx: avg(xs), meanYPx: avg(ys), offsetPx: avg(offsets) }
    } catch (error) { this.set({ error: String(error) }); throw error }
    finally { this.capture = null; this.set({ validating: false, validationPoint: null }) }
  }
}
