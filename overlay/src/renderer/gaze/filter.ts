// One-Euro filter (Casiez et al. 2012), applied to every gaze provider's output (spec §5.1).

export interface OneEuroOptions {
  minCutoff?: number
  beta?: number
  dCutoff?: number
}

export const DEFAULT_ONE_EURO: Required<OneEuroOptions> = { minCutoff: 1.0, beta: 0.007, dCutoff: 1.0 }

const smoothingFactor = (cutoffHz: number, dtSec: number): number => {
  const tau = 1 / (2 * Math.PI * cutoffHz)
  return 1 / (1 + tau / dtSec)
}

/** Filters one scalar. Timestamps are in milliseconds. */
export class OneEuroFilter {
  private readonly minCutoff: number
  private readonly beta: number
  private readonly dCutoff: number
  private xPrev: number | null = null
  private dxPrev = 0
  private tPrev = 0

  constructor(options: OneEuroOptions = {}) {
    const o = { ...DEFAULT_ONE_EURO, ...options }
    this.minCutoff = o.minCutoff
    this.beta = o.beta
    this.dCutoff = o.dCutoff
  }

  filter(x: number, tMs: number): number {
    if (this.xPrev === null) {
      this.xPrev = x
      this.tPrev = tMs
      return x
    }
    // Duplicate or out-of-order timestamps must not divide by zero or run the filter backwards.
    const dt = Math.max((tMs - this.tPrev) / 1000, 1e-3)
    const dx = (x - this.xPrev) / dt
    const aD = smoothingFactor(this.dCutoff, dt)
    const dxHat = aD * dx + (1 - aD) * this.dxPrev
    const cutoff = this.minCutoff + this.beta * Math.abs(dxHat)
    const a = smoothingFactor(cutoff, dt)
    const xHat = a * x + (1 - a) * this.xPrev
    this.xPrev = xHat
    this.dxPrev = dxHat
    this.tPrev = Math.max(tMs, this.tPrev)
    return xHat
  }

  reset(): void {
    this.xPrev = null
    this.dxPrev = 0
  }
}

/** Two independent One-Euro filters for a screen point. */
export class PointFilter {
  private readonly fx: OneEuroFilter
  private readonly fy: OneEuroFilter

  constructor(options: OneEuroOptions = {}) {
    this.fx = new OneEuroFilter(options)
    this.fy = new OneEuroFilter(options)
  }

  filter(x: number, y: number, tMs: number): { x: number; y: number } {
    return { x: this.fx.filter(x, tMs), y: this.fy.filter(y, tMs) }
  }

  reset(): void {
    this.fx.reset()
    this.fy.reset()
  }
}
