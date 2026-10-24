import type { GazeSample } from './GazeProvider'
export interface CalibrationState { validating: boolean; validationPoint: { x: number; y: number } | null; pointIndex: number; error: string | null }
/** Validation never trains the regression. Each displayed dot gets fresh held-out samples. */
export class CalibrationController {
  private state: CalibrationState = { validating: false, validationPoint: null, pointIndex: 0, error: null }
  private readonly listeners = new Set<() => void>()
  private capture: ((sample: GazeSample) => void) | null = null
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  getSnapshot = (): CalibrationState => this.state
  private set(patch: Partial<CalibrationState>): void { this.state = { ...this.state, ...patch }; for (const listener of this.listeners) listener() }
  sample(sample: GazeSample): void { this.capture?.(sample) }
  async validate(points: { x: number; y: number }[]): Promise<{ meanErrorPx: number }> {
    if (this.state.validating) throw new Error('Validation already running')
    if (!points.length || points.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y))) throw new Error('Validation needs finite dot positions')
    this.set({ validating: true, error: null })
    const errors: number[] = []
    try {
      for (const [pointIndex, point] of points.entries()) {
        this.set({ validationPoint: point, pointIndex })
        const start = performance.now()
        const samples: number[] = []
        this.capture = sample => {
          if (sample.t - start >= 400 && sample.confidence > 0) samples.push(Math.hypot(sample.x - point.x, sample.y - point.y))
        }
        await new Promise<void>(resolve => setTimeout(resolve, 1200))
        this.capture = null
        if (!samples.length) throw new Error('No gaze samples during validation; check camera/face tracking')
        errors.push(samples.reduce((sum, e) => sum + e, 0) / samples.length)
      }
      return { meanErrorPx: errors.reduce((sum, e) => sum + e, 0) / errors.length }
    } catch (error) { this.set({ error: String(error) }); throw error }
    finally { this.capture = null; this.set({ validating: false, validationPoint: null }) }
  }
}
