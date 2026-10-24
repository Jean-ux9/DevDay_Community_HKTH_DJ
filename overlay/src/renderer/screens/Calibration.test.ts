// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { agent, calibration, dwell, mounted, platformMock, resetPlatform, setCalibrationState, setGaze } from '../dock/test-platform'
import {
  AUTO_START_S, CAREGIVER_CAPTURE_MS, Calibration, FIXATION_MS, ROUND_CAPTIONS, ROUND_SIZE, SETTLE_MS, TRAIN_POINTS, VALIDATE_POINTS
} from './Calibration'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

const flush = () => act(async () => { await Promise.resolve() })
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const mount = () => {
  const onDone = vi.fn(), onCancel = vi.fn()
  render(createElement(Calibration, { onDone, onCancel }))
  return { onDone, onCancel }
}
const dot = () => document.querySelector<HTMLElement>('.calib-dot')

beforeEach(() => { resetPlatform(); vi.useFakeTimers() })
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('calibration (spec §5.3)', () => {
  it('starts by itself after the countdown, then walks the 9 dots and the 4 held-out checks', async () => {
    const { onDone } = mount()
    expect(calibration.start).not.toHaveBeenCalled()
    for (let s = 0; s < AUTO_START_S; s++) await advance(1000) // one re-render per countdown second
    expect(calibration.start).toHaveBeenCalledTimes(1)
    await flush()
    // No prediction yet: every dot trains after settling and moves on after 1.2 s of samples.
    for (let i = 0; i < TRAIN_POINTS.length; i++) {
      expect(screen.getByText(new RegExp(`${i + 1} of ${TRAIN_POINTS.length}`))).toBeTruthy()
      await advance(SETTLE_MS + FIXATION_MS)
    }
    expect(calibration.train).toHaveBeenCalled()
    expect(calibration.validate).toHaveBeenCalledTimes(1)
    expect(calibration.validate.mock.calls[0]![0]).toHaveLength(VALIDATE_POINTS.length)
    await flush()
    expect(screen.getByText('Average error: 120 px.', { exact: false })).toBeTruthy()
    act(() => { dwell('calib-done') })
    expect(agent.updateSettings).toHaveBeenCalledWith({ gazeSource: 'webgazer', calibrationMode: 'gaze' })
    expect(onDone).toHaveBeenCalled()
  })

  it('trains every dot after the eyes settle, even while the early prediction is far off', async () => {
    mount()
    act(() => { dwell('calib-start-gaze') })
    await flush()
    act(() => setGaze({ point: { x: 5000, y: 5000 }, confidence: 1 }))
    await advance(SETTLE_MS - 100)
    expect(calibration.train).not.toHaveBeenCalled()
    await advance(FIXATION_MS)
    expect(calibration.train).toHaveBeenCalledTimes(FIXATION_MS / 100)
    expect(screen.getByText(/2 of 30/)).toBeTruthy()
  })

  it('above 200 px it offers a redo first', async () => {
    calibration.validate.mockResolvedValueOnce({ meanErrorPx: 260 })
    mount()
    act(() => { dwell('calib-start-gaze') })
    await flush()
    for (let i = 0; i < TRAIN_POINTS.length; i++) await advance(SETTLE_MS + FIXATION_MS)
    await flush()
    expect(screen.getByText('Not accurate enough yet')).toBeTruthy()
    const ids = [...document.querySelectorAll<HTMLElement>('[data-dwell-id]')].map(el => el.dataset.dwellId)
    expect(ids[0]).toBe('calib-redo')
    act(() => { dwell('calib-redo') })
    expect(calibration.start).toHaveBeenCalledTimes(2)
  })

  it('caregiver mode: a click on the dot records it, then the next dot appears', async () => {
    mount()
    act(() => { dwell('calib-start-caregiver') })
    await flush()
    await advance(3000)
    expect(calibration.train).not.toHaveBeenCalled() // waits for the helper's click
    fireEvent.click(dot()!)
    await advance(CAREGIVER_CAPTURE_MS)
    expect(calibration.train).toHaveBeenCalledTimes(CAREGIVER_CAPTURE_MS / 100)
    expect(screen.getByText(/2 of 30/)).toBeTruthy()
    expect(dot()!.tagName).toBe('BUTTON')
  })

  it('draws the validation dot where the platform says', async () => {
    calibration.validate.mockImplementationOnce(() => new Promise(() => {}))
    mount()
    act(() => { dwell('calib-start-gaze') })
    await flush()
    for (let i = 0; i < TRAIN_POINTS.length; i++) await advance(SETTLE_MS + FIXATION_MS)
    act(() => setCalibrationState({ validating: true, validationPoint: { x: 300, y: 200 }, pointIndex: 1 }))
    expect(dot()!.style.left).toBe('300px')
    expect(screen.getByText(/2 of 4/)).toBeTruthy()
  })

  it('if the camera cannot start, offers mouse = gaze instead', async () => {
    calibration.start.mockRejectedValueOnce(new Error('Camera permission is denied'))
    const { onCancel } = mount()
    act(() => { dwell('calib-start-gaze') })
    await flush()
    expect(screen.getByText('Camera permission is denied')).toBeTruthy()
    act(() => { dwell('calib-mouse') })
    expect(platformMock.setGazeSource).toHaveBeenCalledWith('mouse')
    expect(agent.updateSettings).toHaveBeenCalledWith({ gazeSource: 'mouse' })
    expect(onCancel).toHaveBeenCalled()
  })
})

describe('calibration in the app', () => {
  it('is offered once at launch with eye tracking and returns to the dock', async () => {
    act(() => setGaze({ source: 'webgazer' }))
    render(createElement(App))
    expect(document.querySelector('.calibration-screen')).toBeTruthy()
    act(() => { dwell('calib-cancel') })
    expect(document.querySelector('.calibration-screen')).toBeNull()
    expect(mounted('suggest-now')).toBeTruthy()
  })

  it('STOP stays reachable during calibration and leaves it', () => {
    act(() => setGaze({ source: 'webgazer' }))
    render(createElement(App))
    act(() => { dwell('stop') })
    expect(document.querySelector('.calibration-screen')).toBeNull()
    expect(mounted('suggest-now')).toBeTruthy()
  })

  it('30 dots in 3 head-pose rounds, each round spread over the whole screen', async () => {
    expect(TRAIN_POINTS).toHaveLength(30)
    for (let r = 0; r < 3; r++) {
      const round = TRAIN_POINTS.slice(r * ROUND_SIZE, (r + 1) * ROUND_SIZE)
      expect(Math.min(...round.map(p => p[0]))).toBeLessThan(0.25)
      expect(Math.max(...round.map(p => p[0]))).toBeGreaterThan(0.75)
      expect(Math.min(...round.map(p => p[1]))).toBeLessThan(0.3)
      expect(Math.max(...round.map(p => p[1]))).toBeGreaterThan(0.7)
    }
    act(() => setGaze({ source: 'webgazer' }))
    render(createElement(App))
    act(() => { dwell('calib-start-gaze') })
    await flush()
    expect(screen.getByText(new RegExp(ROUND_CAPTIONS[0]))).toBeTruthy()
    for (let i = 0; i < ROUND_SIZE; i++) await advance(SETTLE_MS + FIXATION_MS)
    expect(screen.getByText(new RegExp(ROUND_CAPTIONS[1]))).toBeTruthy()
  })

  it('no training dot sits under STOP (top-right 160×160 + margin)', () => {
    for (const [fx, fy] of TRAIN_POINTS) {
      const x = fx * 1280, y = fy * 800 // a small screen is the worst case
      expect(x + 36 < 1280 - 24 - 160 || y - 36 > 24 + 160, `${fx},${fy}`).toBe(true)
    }
  })

  it('is not shown with mouse = gaze', () => {
    render(createElement(App))
    expect(document.querySelector('.calibration-screen')).toBeNull()
  })
})
