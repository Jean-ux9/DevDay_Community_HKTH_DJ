import { afterEach, describe, expect, it, vi } from 'vitest'
import { CalibrationController } from './calibration'
afterEach(() => vi.useRealTimers())
describe('held-out calibration validation', () => {
  it('publishes dot positions and averages fresh raw errors with fake time', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'performance'] })
    const controller = new CalibrationController()
    const result = controller.validate([{ x: 100, y: 100 }, { x: 300, y: 300 }])
    expect(controller.getSnapshot().validationPoint).toEqual({ x: 100, y: 100 })
    await vi.advanceTimersByTimeAsync(500)
    controller.sample({ x: 103, y: 104, t: performance.now(), confidence: 1 })
    await vi.advanceTimersByTimeAsync(700)
    expect(controller.getSnapshot().validationPoint).toEqual({ x: 300, y: 300 })
    await vi.advanceTimersByTimeAsync(500)
    controller.sample({ x: 306, y: 308, t: performance.now(), confidence: 1 })
    await vi.advanceTimersByTimeAsync(700)
    expect(await result).toEqual({ meanErrorPx: 7.5 })
    expect(controller.getSnapshot().validating).toBe(false)
  })
  it('rejects an empty pass and missing samples instead of claiming zero error', async () => {
    vi.useFakeTimers()
    const controller = new CalibrationController()
    await expect(controller.validate([])).rejects.toThrow('positions')
    const result = expect(controller.validate([{ x: 0, y: 0 }])).rejects.toThrow('No gaze samples')
    await vi.advanceTimersByTimeAsync(1200)
    await result
    expect(controller.getSnapshot().error).toContain('No gaze samples')
  })
})
