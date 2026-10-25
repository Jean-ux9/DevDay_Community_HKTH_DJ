// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { agent, baseSession, calibration, dwell, mounted, platformMock, resetPlatform, setGaze, setSession, targets } from '../dock/test-platform'
import { DWELL_MAX_MS, DWELL_MIN_MS, SETTINGS_DWELL_MS, SettingsPanel } from './Settings'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

const settings = (patch: object = {}) => ({ settings: { ...baseSession().settings!, ...patch } })
const mount = () => {
  const onRecalibrate = vi.fn()
  render(createElement(SettingsPanel, { onRecalibrate }))
  return { onRecalibrate }
}

beforeEach(() => resetPlatform())
afterEach(cleanup)

describe('settings panel', () => {
  it('shows the saved dwell time and changes it in 100 ms steps within 500–2000', () => {
    mount()
    expect(screen.getByText('800 ms')).toBeTruthy()
    act(() => { dwell('set-dwell-faster') })
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ dwellMs: 700 })
    act(() => { dwell('set-dwell-slower') })
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ dwellMs: 900 })
    act(() => setSession(settings({ dwellMs: DWELL_MIN_MS })))
    expect(dwell('set-dwell-faster')).toBe(false)
    act(() => setSession(settings({ dwellMs: DWELL_MAX_MS })))
    expect(dwell('set-dwell-slower')).toBe(false)
  })

  it('only displays values from settings_result, not its own guesses', () => {
    mount()
    act(() => { dwell('set-dwell-slower') })
    expect(screen.getByText('800 ms')).toBeTruthy()
    act(() => setSession(settings({ dwellMs: 900 })))
    expect(screen.getByText('900 ms')).toBeTruthy()
  })

  it('toggles text size; no calibration-helper or demo-mode card for users', () => {
    mount()
    act(() => { dwell('set-density') })
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ density: 'compact' })
    expect(mounted('set-calib-mode')).toBeNull()
    expect(mounted('set-demo')).toBeNull()
  })

  it('switching to eye tracking goes through calibration; switching to the mouse is immediate', () => {
    const { onRecalibrate } = mount()
    act(() => { dwell('set-source') })
    expect(onRecalibrate).toHaveBeenCalledTimes(1)
    expect(platformMock.setGazeSource).not.toHaveBeenCalled()
    act(() => setGaze({ source: 'webgazer' }))
    act(() => { dwell('set-source') })
    expect(platformMock.setGazeSource).toHaveBeenCalledWith('mouse')
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ gazeSource: 'mouse' })
  })

  it('every setting is also mouse-clickable for a caregiver', () => {
    mount()
    const card = mounted('set-density')!
    expect(card.hasAttribute('data-caregiver-clickable')).toBe(true)
    fireEvent.click(card)
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ density: 'compact' })
  })

  it('the pointer card toggles mouse <-> head tracking (the custom-calibration pointer)', () => {
    const { onRecalibrate } = mount()
    expect(mounted('set-source')!.textContent).toContain('Switch to head tracking, calibrates first')
    act(() => { dwell('set-source') })
    expect(onRecalibrate).toHaveBeenLastCalledWith('head')
    act(() => setGaze({ source: 'head' }))
    act(() => { dwell('set-source') })
    expect(platformMock.setGazeSource).toHaveBeenLastCalledWith('mouse')
  })

  it('switching to head tracking once calibrated (now or in an earlier launch) is instant', () => {
    platformMock.isPointerTrained.mockReturnValue(true)
    const { onRecalibrate } = mount()
    expect(mounted('set-source')!.textContent).not.toContain('calibrates first')
    act(() => { dwell('set-source') })
    expect(platformMock.setGazeSource).toHaveBeenCalledWith('head')
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ gazeSource: 'webgazer' }) // 'webgazer' = camera pointer
    expect(onRecalibrate).not.toHaveBeenCalled()
  })

  it('demo mode (a developer flag): shortcut hints go, Quit goes, the overlay gets .demo', () => {
    render(createElement(App))
    expect(mounted('quit-app')).toBeTruthy()
    act(() => { dwell('settings-open') })
    expect(mounted('set-click-mode')!.textContent).toContain('⌃⌥⌘D')
    act(() => setGaze({ demoMode: true }))
    expect(mounted('set-click-mode')!.textContent).not.toContain('⌃⌥⌘D')
    expect(mounted('quit-app')).toBeNull()
    expect(document.querySelector('.overlay')!.className).toContain('demo')
  })

  it('Settings has no Done card: STOP leaves it', () => {
    mount()
    expect(mounted('set-close')).toBeNull()
  })

  it('head pose as the pointer turns on the head-pointer layout by itself', () => {
    render(createElement(App))
    act(() => setGaze({ source: 'head' }))
    expect(document.querySelector('.overlay')!.className).toContain('head-pointer')
  })

  it('Recenter is offered for camera pointers only', () => {
    const onRecenter = vi.fn()
    render(createElement(SettingsPanel, { onRecalibrate: vi.fn(), onRecenter }))
    expect(mounted('set-recenter')).toBeNull()
    act(() => setGaze({ source: 'head' }))
    act(() => { dwell('set-recenter') })
    expect(onRecenter).toHaveBeenCalledTimes(1)
  })

  it('launch calibration keeps running after the pointer counts as trained', () => {
    render(createElement(App))
    act(() => setGaze({ source: 'head' }))
    expect(document.querySelector('.calibration-screen')).toBeTruthy()
    platformMock.isPointerTrained.mockReturnValue(true) // a few dots in: enough samples to predict
    act(() => setGaze({ source: 'head' }))
    expect(document.querySelector('.calibration-screen')).toBeTruthy()
  })

  it('the Recenter screen runs one centre dot and returns to the dock', async () => {
    vi.useFakeTimers()
    platformMock.isPointerTrained.mockReturnValue(true) // calibrated earlier: no calibration on launch
    render(createElement(App))
    act(() => setGaze({ source: 'head' }))
    act(() => { dwell('settings-open') })
    act(() => { dwell('set-recenter') })
    expect(screen.getByText(/Recenter: turn your nose to the dot/)).toBeTruthy()
    expect(calibration.recenter).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(mounted('suggest-now')).toBeTruthy()
    vi.useRealTimers()
  })

  it('custom calibration (default) shows the calibration cards and a card into macOS Head Pointer mode', () => {
    mount()
    for (const id of ['set-source', 'set-recalibrate']) expect(mounted(id)).toBeTruthy()
    expect(mounted('set-blink')).toBeNull()
    act(() => { dwell('set-head-pointer') })
    expect(platformMock.setHeadPointer).toHaveBeenCalledWith(true)
  })

  it('macOS Head Pointer mode hides every calibration card and pulls targets in from the edges', () => {
    render(createElement(App))
    act(() => setGaze({ headPointer: true }))
    expect(document.querySelector('.overlay')!.className).toContain('head-pointer')
    act(() => { dwell('settings-open') })
    for (const id of ['set-source', 'set-recalibrate', 'set-recenter']) expect(mounted(id)).toBeNull()
    act(() => { dwell('set-head-pointer') })
    expect(platformMock.setHeadPointer).toHaveBeenCalledWith(false)
  })

  it('toggles click mode (dwell off, clicks on) without touching saved settings', () => {
    mount()
    act(() => { dwell('set-click-mode') })
    expect(platformMock.setClickMode).toHaveBeenCalledWith(true)
    expect(agent.updateSettings).not.toHaveBeenCalled()
    expect(mounted('set-click-mode')!.textContent).toContain('Select: by clicking')
  })
})

describe('getting to Settings and Recalibrate', () => {
  it('a slow-dwell corner target opens Settings while idle; Recalibrate opens the dots', () => {
    render(createElement(App))
    expect(targets.get('settings-open')!.dwellMs).toBe(SETTINGS_DWELL_MS)
    act(() => { dwell('settings-open') })
    expect(mounted('set-recalibrate')).toBeTruthy()
    expect(mounted('tab-auto')).toBeNull()
    act(() => { dwell('set-recalibrate') })
    expect(document.querySelector('.calibration-screen')).toBeTruthy()
    act(() => { dwell('calib-cancel') })
    expect(mounted('suggest-now')).toBeTruthy()
  })

  it('in click mode every target takes real clicks and the status row says so', () => {
    render(createElement(App))
    expect(mounted('suggest-now')!.hasAttribute('data-caregiver-clickable')).toBe(false)
    act(() => setGaze({ clickMode: true }))
    expect(screen.getByText(/Click mode/)).toBeTruthy()
    fireEvent.click(mounted('suggest-now')!)
    expect(agent.suggestNow).toHaveBeenCalledTimes(1)
  })

  it('STOP from the keyboard goes back to the main menu (Auto) without asking for suggestions', () => {
    resetPlatform({ mode: 'type' })
    render(createElement(App))
    expect(mounted('key-ABC')).toBeTruthy()
    fireEvent.click(mounted('stop')!)
    expect(agent.stop).toHaveBeenCalledWith('gaze')
    expect(agent.setMode).toHaveBeenCalledWith('auto')
    expect(agent.suggestNow).not.toHaveBeenCalled()
  })

  it('STOP in Auto with suggestions showing resets to the empty main menu', () => {
    resetPlatform({ list: { listId: 'L1', source: 'suggestions', app: 'Mail', windowKey: 'k', cached: false,
      items: [{ id: 's1', label: 'Reply', kind: 'task', risky: false }] } })
    render(createElement(App))
    fireEvent.click(mounted('stop')!)
    expect(agent.setMode).toHaveBeenCalledWith('auto')
    expect(agent.suggestNow).not.toHaveBeenCalled()
  })

  it('STOP closes Settings when nothing is running', () => {
    render(createElement(App))
    act(() => { dwell('settings-open') })
    expect(mounted('set-dwell-faster')).toBeTruthy()
    act(() => { dwell('stop') })
    expect(mounted('set-dwell-faster')).toBeNull()
    expect(mounted('suggest-now')).toBeTruthy()
  })

  it('Quit is a slow-dwell, clickable corner target that quits the app', () => {
    render(createElement(App))
    expect(targets.get('quit-app')!.dwellMs).toBe(2000)
    fireEvent.click(mounted('quit-app')!)
    expect(platformMock.quitApp).toHaveBeenCalledTimes(1)
  })

  it('the corner target is gone while a task runs', () => {
    resetPlatform({ task: { taskId: 't1', state: 'running', step: 1, maxSteps: 15, message: 'Working…' } })
    render(createElement(App))
    expect(mounted('settings-open')).toBeNull()
  })

  it('density from settings applies to the whole overlay', () => {
    resetPlatform(settings({ density: 'compact' }))
    render(createElement(App))
    expect(document.querySelector('.overlay')!.className).toContain('density-compact')
  })
})
