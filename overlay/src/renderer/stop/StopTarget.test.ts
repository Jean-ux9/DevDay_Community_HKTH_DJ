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

  it('during a task it sends stop{reason:"gaze"} and nothing else', () => {
    const onIdle = vi.fn()
    resetPlatform({ task })
    render(createElement(StopTarget, { onIdle }))
    act(() => { dwell('stop') })
    expect(agent.stop).toHaveBeenCalledWith('gaze')
    expect(onIdle).not.toHaveBeenCalled()
  })

  it('with nothing running it is still armed: stop goes out (an agent no-op) and the UI goes back to the dock', () => {
    const onIdle = vi.fn()
    render(createElement(StopTarget, { onIdle }))
    expect(mounted('stop')!.textContent).toContain('Main menu')
    act(() => { dwell('stop') })
    expect(agent.stop).toHaveBeenCalledWith('gaze')
    expect(onIdle).toHaveBeenCalledTimes(1)
  })

  it('a plan that is starting counts as running', () => {
    const onIdle = vi.fn()
    resetPlatform({ pendingSelect: 'm1' })
    render(createElement(StopTarget, { onIdle }))
    act(() => { dwell('stop') })
    expect(agent.stop).toHaveBeenCalledWith('gaze')
    expect(onIdle).not.toHaveBeenCalled()
  })

  it('stays disarmed while stopping', () => {
    resetPlatform({ task, stopping: true })
    render(createElement(StopTarget))
    expect(dwell('stop')).toBe(false)
    expect(mounted('stop')!.textContent).toContain('Stopping…')
  })
})
