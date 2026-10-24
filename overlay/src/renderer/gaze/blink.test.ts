import { describe, expect, it, vi } from 'vitest'
import { BlinkDetector, eyeAspectRatio } from './blink'
import { DwellManager } from '../dwell/DwellManager'
const blink = (detector: BlinkDetector, start: number, duration: number) => {
  for (let t = start; t < start + duration; t += 20) detector.update(0.1, t)
  detector.update(0.3, start + duration)
}
describe('blink selection', () => {
  it('pauses on a normal blink and ignores durations <=400 ms', () => {
    const select = vi.fn(), pause = vi.fn(), detector = new BlinkDetector(select, pause)
    blink(detector, 0, 200); blink(detector, 500, 400)
    expect(select).not.toHaveBeenCalled()
    expect(pause).toHaveBeenCalledWith(true)
    expect(pause).toHaveBeenLastCalledWith(false)
  })
  it('selects once on reopening after >400 ms, using the manager armed-target rule', () => {
    const manager = new DwellManager(), select = vi.fn()
    manager.register({ id: 'a', rect: { x: 0, y: 0, w: 160, h: 120 }, variant: 'card', dwellMs: 2000, onSelect: select })
    const detector = new BlinkDetector(t => manager.blinkSelect(t), p => manager.setPaused(p))
    for (let t = 0; t <= 350; t += 10) manager.update({ x: 80, y: 60, t })
    blink(detector, 360, 500)
    detector.update(0.3, 880)
    expect(select).toHaveBeenCalledTimes(1)
  })
  it('does not treat lost face tracking as a long blink', () => {
    const select = vi.fn(), detector = new BlinkDetector(select, vi.fn())
    detector.update(0.1, 0); detector.update(null, 100); detector.update(0.3, 700)
    expect(select).not.toHaveBeenCalled()
    detector.update(0.1, 800); detector.update(0.3, 1500)
    expect(select).not.toHaveBeenCalled()
  })
  it('computes EAR from landmarks and tolerates missing landmarks', () => {
    const points = [{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 3, y: 1 }, { x: 4, y: 0 }, { x: 3, y: -1 }, { x: 1, y: -1 }]
    expect(eyeAspectRatio(points, [0, 1, 2, 3, 4, 5])).toBeCloseTo(0.5)
    expect(eyeAspectRatio([], [0, 1, 2, 3, 4, 5])).toBe(1)
  })
})
