import { describe, expect, it } from 'vitest'
import { cubicBezier, traceEase } from './trace'

describe('dwell fill pacing', () => {
  it('eases from exactly 0 to exactly 1, so the fill takes the whole dwell time', () => {
    expect(traceEase(0)).toBe(0)
    expect(traceEase(1)).toBe(1)
    for (let x = 0.05; x < 1; x += 0.05) expect(traceEase(x)).toBeGreaterThan(traceEase(x - 0.05)) // always forward
    expect(traceEase(0.15)).toBeGreaterThan(0.03) // gets going early…
    expect(traceEase(0.15)).toBeLessThan(0.15) // …but still accelerates
    expect(traceEase(0.85)).toBeGreaterThan(0.85) // and slows into the finish
  })

  it('matches a known cubic-bezier point', () => {
    expect(cubicBezier(0, 0, 1, 1)(0.3)).toBeCloseTo(0.3, 4) // linear
  })
})
