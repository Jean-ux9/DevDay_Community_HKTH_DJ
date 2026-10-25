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
  it('the eye at the top right hides the dock (closed eye) and shows it again; the choice is remembered', () => {
    const view = render(createElement(App))
    expect(mounted('dock-hide')!.textContent).toContain('Hide')
    act(() => { dwell('dock-hide') })
    expect(mounted('suggest-now')).toBeNull()
    expect(mounted('dock-hide')!.textContent).toContain('Show')
    expect(mounted('dock-hide')!.className).toContain('is-hidden')
    expect(mounted('stop')).toBeTruthy()
    expect(mounted('settings-open')).toBeNull()
    view.unmount()
    render(createElement(App))
    expect(mounted('dock-hide')!.textContent).toContain('Show') // still hidden after a relaunch
    act(() => { dwell('dock-hide') })
    expect(mounted('suggest-now')).toBeTruthy()
  })

  it('Quit sits alone top-left; Hide, Settings, Back form the right column, top to bottom', () => {
    render(createElement(App))
    const ids = (sel: string) => [...document.querySelectorAll(`${sel} > [data-dwell-id]`)].map(el => el.getAttribute('data-dwell-id'))
    expect(ids('.corner-stack.is-left')).toEqual(['quit-app'])
    expect(ids('.corner-stack:not(.is-left)')).toEqual(['dock-hide', 'settings-open', 'stop'])
  })

  it('the eye stays at the top right while typing too', () => {
    render(createElement(App))
    act(() => setSession({ mode: 'type' }))
    expect(mounted('dock-hide')!.className).toContain('corner-hide')
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
