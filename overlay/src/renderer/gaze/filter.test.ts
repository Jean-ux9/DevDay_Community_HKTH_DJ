import { describe, expect, it } from 'vitest'
import { OneEuroFilter, PointFilter } from './filter'

// Deterministic pseudo-random noise in [-1, 1].
const rng = (seed: number) => () => {
  seed = (seed * 1664525 + 1013904223) % 4294967296
  return (seed / 4294967296) * 2 - 1
}

const std = (xs: number[]) => {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length)
}

describe('OneEuroFilter', () => {
  it('passes the first sample through unchanged', () => {
    expect(new OneEuroFilter().filter(420, 0)).toBe(420)
  })

  it('converges to a constant input', () => {
    const f = new OneEuroFilter()
    let y = 0
    for (let i = 0; i < 300; i++) y = f.filter(100, i * 16.7)
    expect(y).toBeCloseTo(100, 6)
  })

  it('removes most of the jitter around a fixed point', () => {
    const noise = rng(1)
    const f = new OneEuroFilter()
    const raw: number[] = []
    const out: number[] = []
    for (let i = 0; i < 600; i++) {
      const x = 500 + noise() * 30
      raw.push(x)
      out.push(f.filter(x, i * 16.7))
    }
    expect(std(out.slice(60))).toBeLessThan(std(raw.slice(60)) * 0.4)
  })

  it('catches up after a fast jump (speed raises the cutoff)', () => {
    const f = new OneEuroFilter()
    for (let i = 0; i < 60; i++) f.filter(100, i * 16.7)
    let y = 0
    for (let i = 60; i < 120; i++) y = f.filter(900, i * 16.7)
    expect(Math.abs(y - 900)).toBeLessThan(5)
  })

  it('with beta=0 it is a plain low-pass: slower to follow the same jump', () => {
    const slow = new OneEuroFilter({ beta: 0 })
    const fast = new OneEuroFilter({ beta: 0.007 })
    for (let i = 0; i < 60; i++) {
      slow.filter(100, i * 16.7)
      fast.filter(100, i * 16.7)
    }
    let ys = 0
    let yf = 0
    for (let i = 60; i < 75; i++) {
      ys = slow.filter(900, i * 16.7)
      yf = fast.filter(900, i * 16.7)
    }
    expect(Math.abs(900 - yf)).toBeLessThan(Math.abs(900 - ys))
  })

  it('survives duplicate and backwards timestamps', () => {
    const f = new OneEuroFilter()
    f.filter(10, 100)
    const a = f.filter(20, 100)
    const b = f.filter(30, 50)
    expect(Number.isFinite(a)).toBe(true)
    expect(Number.isFinite(b)).toBe(true)
  })

  it('reset forgets the previous sample', () => {
    const f = new OneEuroFilter()
    f.filter(0, 0)
    f.filter(0, 16)
    f.reset()
    expect(f.filter(777, 32)).toBe(777)
  })
})

describe('PointFilter', () => {
  it('filters x and y independently', () => {
    const p = new PointFilter()
    expect(p.filter(10, 20, 0)).toEqual({ x: 10, y: 20 })
    const next = p.filter(10, 200, 16)
    expect(next.x).toBe(10)
    expect(next.y).toBeGreaterThan(20)
    expect(next.y).toBeLessThan(200)
  })
})
