// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { agent, baseSession, dwell, mounted, resetPlatform, setGaze, setSession } from '../dock/test-platform'
import { Onboarding, RESTART_HINT_MS } from './Onboarding'
import { missingPermissions } from './permissions'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

const perms = (accessibility: boolean, screen_recording: boolean, camera: 'granted' | 'denied' | 'not-determined' | 'unknown') =>
  ({ permissions: { accessibility, screen_recording, camera } })

beforeEach(() => { resetPlatform(); vi.useFakeTimers() })
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('which permissions block the overlay', () => {
  it('needs Accessibility and Screen Recording always, the camera only for eye tracking', () => {
    expect(missingPermissions(baseSession(perms(false, true, 'unknown')), 'mouse')).toEqual(['accessibility'])
    expect(missingPermissions(baseSession(perms(true, true, 'denied')), 'mouse')).toEqual([])
    expect(missingPermissions(baseSession(perms(true, true, 'denied')), 'webgazer')).toEqual(['camera'])
    expect(missingPermissions(baseSession(perms(true, true, 'granted')), 'webgazer')).toEqual([])
    expect(missingPermissions(baseSession(perms(true, true, 'not-determined')), 'webgazer')).toEqual(['camera'])
    expect(missingPermissions(baseSession(perms(true, true, 'unknown')), 'webgazer')).toEqual([])
    expect(missingPermissions(baseSession({ permissions: null }), 'webgazer')).toEqual([])
  })
})

describe('permissions checklist (spec §11)', () => {
  it('shows each row in words and opens the right Settings pane by dwell or by click', () => {
    resetPlatform(perms(false, false, 'granted'))
    render(createElement(Onboarding))
    expect(screen.getAllByText('Not allowed')).toHaveLength(2)
    act(() => { dwell('perm-open-accessibility') })
    expect(agent.openSettingsPane).toHaveBeenCalledWith('accessibility')
    fireEvent.click(mounted('perm-open-screen_recording')!.querySelector('button')!)
    expect(agent.openSettingsPane).toHaveBeenCalledWith('screen_recording')
    expect(mounted('perm-open-camera')).toBeNull()
  })

  it('suggests restarting the terminal when a row stays red 10 s after "Open Settings"', () => {
    resetPlatform(perms(false, true, 'granted'))
    render(createElement(Onboarding))
    act(() => { dwell('perm-open-accessibility') })
    act(() => { vi.advanceTimersByTime(RESTART_HINT_MS - 1000) })
    expect(screen.queryByText(/Quit and reopen the terminal app/)).toBeNull()
    act(() => { vi.advanceTimersByTime(1000) })
    expect(screen.getByText(/Quit and reopen the terminal app/)).toBeTruthy()
  })

  it('asks for the camera once the agent permissions are allowed, not before', () => {
    resetPlatform(perms(false, true, 'not-determined'))
    act(() => setGaze({ source: 'webgazer' }))
    render(createElement(Onboarding))
    expect(agent.openSettingsPane).not.toHaveBeenCalledWith('camera')
    act(() => setSession(perms(true, true, 'not-determined')))
    expect(agent.openSettingsPane).toHaveBeenCalledWith('camera')
    expect(agent.openSettingsPane).toHaveBeenCalledTimes(1)
  })

  it('takes over the idle overlay, never a running task, and leaves when all rows are green', () => {
    resetPlatform(perms(true, false, 'granted'))
    render(createElement(App))
    expect(document.querySelector('.onboarding')).toBeTruthy()
    act(() => setSession({ task: { taskId: 't1', state: 'running', step: 1, maxSteps: 15, message: 'Working…' } }))
    expect(document.querySelector('.onboarding')).toBeNull()
    act(() => setSession({ task: null }))
    expect(document.querySelector('.onboarding')).toBeTruthy()
    act(() => setSession(perms(true, true, 'granted')))
    expect(document.querySelector('.onboarding')).toBeNull()
    expect(mounted('suggest-now')).toBeTruthy()
  })
})
