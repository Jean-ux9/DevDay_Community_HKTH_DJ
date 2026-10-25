// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { dwell, mounted, plan, resetPlatform, setSession } from './test-platform'

vi.mock('../platform', async () => (await import('./test-platform')).platformMock)

beforeEach(() => { localStorage.clear(); resetPlatform() })
afterEach(cleanup)

describe('collapsible dock', () => {
  it('Hide shrinks the dock to one Open pill; Open brings it back; the choice is remembered', () => {
    const view = render(createElement(App))
    act(() => { dwell('dock-hide') })
    expect(mounted('suggest-now')).toBeNull()
    expect(mounted('dock-open')).toBeTruthy()
    expect(mounted('stop')).toBeTruthy()
    expect(mounted('settings-open')).toBeNull()
    view.unmount()
    render(createElement(App))
    expect(mounted('dock-open')).toBeTruthy() // still hidden after a relaunch
    act(() => { dwell('dock-open') })
    expect(mounted('suggest-now')).toBeTruthy()
  })

  it('opens by itself when the agent has something for the user', () => {
    render(createElement(App))
    act(() => { dwell('dock-hide') })
    act(() => setSession({ list: { listId: 'L1', source: 'suggestions', app: 'Mail', windowKey: 'k', cached: false,
      items: [plan('s1', 'Reply: sounds good')] } }))
    expect(mounted('suggestion-L1-s1')).toBeTruthy()
    act(() => { dwell('dock-hide') })
    act(() => setSession({ task: { taskId: 't', state: 'waiting_user', step: 2, maxSteps: 15, message: '' },
      choice: { requestId: 'c', taskId: 't', question: 'Which date?', options: [{ id: 'a', label: 'Fri' }, { id: 'b', label: 'Sat' }] } }))
    expect(mounted('choice-c-a')).toBeTruthy()
  })
})
