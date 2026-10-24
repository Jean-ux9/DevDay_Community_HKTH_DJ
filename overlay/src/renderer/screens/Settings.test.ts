// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { agent, baseSession, dwell, mounted, platformMock, resetPlatform, setGaze, setSession, targets } from '../dock/test-platform'
import { DWELL_MAX_MS, DWELL_MIN_MS, SETTINGS_DWELL_MS, SettingsPanel } from './Settings'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

const settings = (patch: object = {}) => ({ settings: { ...baseSession().settings!, ...patch } })
const mount = () => {
  const onRecalibrate = vi.fn(), onClose = vi.fn()
  render(createElement(SettingsPanel, { onRecalibrate, onClose }))
  return { onRecalibrate, onClose }
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

  it('toggles text size, blink select and the calibration helper', () => {
    mount()
    act(() => { dwell('set-density') })
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ density: 'compact' })
    act(() => { dwell('set-blink') })
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ blinkSelect: true })
    act(() => { dwell('set-calib-mode') })
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ calibrationMode: 'caregiver' })
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
    const button = mounted('set-density')!.querySelector('button')!
    expect(button.hasAttribute('data-caregiver-clickable')).toBe(true)
    fireEvent.click(button)
    expect(agent.updateSettings).toHaveBeenLastCalledWith({ density: 'compact' })
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
