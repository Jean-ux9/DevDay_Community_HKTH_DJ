// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { agent, dwell, mounted, resetPlatform, setSession, targets } from '../dock/test-platform'
import { StopTarget } from './StopTarget'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

const task = { taskId: 't1', state: 'running' as const, step: 1, maxSteps: 15, message: 'Opening Mail…' }

beforeEach(() => resetPlatform())
afterEach(cleanup)

describe('STOP target', () => {
  it('is always on screen and uses the STOP variant (400 ms, no cooldown)', () => {
    render(createElement(StopTarget))
    expect(mounted('stop')).toBeTruthy()
    expect(targets.get('stop')!.variant).toBe('stop')
  })

  it('is armed only while a task exists, and sends stop{reason:"gaze"}', () => {
    render(createElement(StopTarget))
    expect(dwell('stop')).toBe(false)
    act(() => setSession({ task }))
    act(() => { dwell('stop') })
    expect(agent.stop).toHaveBeenCalledWith('gaze')
  })

  it('stays disarmed while stopping', () => {
    resetPlatform({ task, stopping: true })
    render(createElement(StopTarget))
    expect(dwell('stop')).toBe(false)
    expect(mounted('stop')!.textContent).toContain('Stopping…')
  })
})
