// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { agent, dwell, mounted, resetPlatform, setSession } from './test-platform'

vi.mock('../platform', async () => (await import('./test-platform')).platformMock)

beforeEach(() => resetPlatform())
afterEach(cleanup)

describe('Auto | Type tabs (spec §7: suggestions on demand only)', () => {
  it('launching in Auto asks for nothing, even once the agent becomes ready', () => {
    resetPlatform({ ready: false, connection: 'connecting' })
    render(createElement(App))
    act(() => setSession({ ready: true, connection: 'open' }))
    act(() => setSession({ mode: 'auto' }))
    expect(agent.suggestNow).not.toHaveBeenCalled()
    expect(agent.setMode).not.toHaveBeenCalled()
  })

  it('switching to Auto sets the mode, then asks for suggestions exactly once', () => {
    resetPlatform({ mode: 'type' })
    render(createElement(App))
    act(() => { dwell('tab-auto') })
    expect(agent.setMode).toHaveBeenCalledWith('auto')
    expect(agent.suggestNow).toHaveBeenCalledTimes(1)
    expect(agent.setMode.mock.invocationCallOrder[0]).toBeLessThan(agent.suggestNow.mock.invocationCallOrder[0]!)

    act(() => setSession({ mode: 'auto' }))
    expect(agent.suggestNow).toHaveBeenCalledTimes(1)
  })

  it('switching to Type only sets the mode', () => {
    render(createElement(App))
    act(() => { dwell('tab-type') })
    expect(agent.setMode).toHaveBeenCalledWith('type')
    expect(agent.suggestNow).not.toHaveBeenCalled()
  })

  it('the active tab cannot be selected again', () => {
    render(createElement(App))
    expect(mounted('tab-auto')!.getAttribute('aria-disabled')).toBe('true')
    expect(dwell('tab-auto')).toBe(false)
    expect(agent.suggestNow).not.toHaveBeenCalled()
  })

  it('the dock collapses to the status pill only while a task runs, with STOP armed', () => {
    render(createElement(App))
    expect(mounted('stop')!.getAttribute('aria-disabled')).toBe('true')
    act(() => setSession({ task: { taskId: 't1', state: 'running', step: 3, maxSteps: 15, message: 'Opening Messages…' } }))
    expect(mounted('tab-auto')).toBeNull()
    expect(document.querySelector('.status-pill')!.textContent).toContain('Step 3 of 15')
    expect(document.querySelector('.status-pill')!.textContent).toContain('Opening Messages…')
    expect(mounted('stop')!.getAttribute('aria-disabled')).toBeNull()
  })
})
