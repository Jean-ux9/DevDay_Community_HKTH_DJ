// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AutoDock } from './AutoDock'
import { agent, dwell, mounted, plan, resetPlatform, setSession, targetIds } from './test-platform'

vi.mock('../platform', async () => (await import('./test-platform')).platformMock)

const suggestions = (listId = 'L1') => ({
  listId, source: 'suggestions' as const, app: 'Mail', windowKey: 'mail|inbox', cached: false,
  items: [plan('s1', 'Reply: sounds good', { risky: true, detail: 'Mail → Alex' }), plan('s2', 'Archive this email'),
    plan('s3', 'Remind me tomorrow')]
})

beforeEach(() => resetPlatform())
afterEach(cleanup)

describe('Auto dock and the "Suggest now" card', () => {
  it('shows "Suggest now" first and "Something else" last, with a hint before any suggestion', () => {
    render(createElement(AutoDock))
    expect(targetIds()).toEqual(['suggest-now', 'auto-other'])
    expect(screen.getByText('No suggestions yet')).toBeTruthy()
  })

  it('a dwell on "Suggest now" calls agent.suggestNow() exactly once', () => {
    render(createElement(AutoDock))
    act(() => { dwell('suggest-now') })
    expect(agent.suggestNow).toHaveBeenCalledTimes(1)
    expect(agent.setMode).not.toHaveBeenCalled()
  })

  it('shows a spinner and is disabled while suggestPending, so repeated dwells queue nothing', () => {
    render(createElement(AutoDock))
    act(() => setSession({ suggestPending: true }))
    const card = mounted('suggest-now')!
    expect(card.getAttribute('aria-disabled')).toBe('true')
    expect(card.querySelector('.spinner')).toBeTruthy()
    expect(card.textContent).toContain('Thinking…')
    expect(dwell('suggest-now')).toBe(false)
    expect(agent.suggestNow).not.toHaveBeenCalled()

    act(() => setSession({ suggestPending: false, list: suggestions() }))
    expect(mounted('suggest-now')!.getAttribute('aria-disabled')).toBeNull()
    expect(mounted('suggest-now')!.querySelector('.spinner')).toBeNull()
  })

  it('is disabled before the agent is ready', () => {
    resetPlatform({ ready: false })
    render(createElement(AutoDock))
    expect(dwell('suggest-now')).toBe(false)
  })

  it('suggestions replace the cards next to it; "Something else" stays last', () => {
    render(createElement(AutoDock))
    act(() => setSession({ list: suggestions('L1') }))
    expect(targetIds()).toEqual(['suggest-now', 'suggestion-L1-s1', 'suggestion-L1-s2', 'suggestion-L1-s3', 'auto-other'])
    expect(screen.getByText('Asks you first')).toBeTruthy()

    act(() => setSession({ list: { ...suggestions('L2'), items: [plan('s9', 'Play Deep Focus')] } }))
    expect(targetIds()).toEqual(['suggest-now', 'suggestion-L2-s9', 'auto-other'])
  })

  it('selecting a suggestion starts it with plan_select on the current list', () => {
    render(createElement(AutoDock))
    act(() => setSession({ list: suggestions('L7') }))
    act(() => { dwell('suggestion-L7-s2') })
    expect(agent.selectPlan).toHaveBeenCalledWith('L7', 's2')
  })

  it('"Something else" switches to Type without asking for suggestions', () => {
    render(createElement(AutoDock))
    act(() => { dwell('auto-other') })
    expect(agent.setMode).toHaveBeenCalledWith('type')
    expect(agent.suggestNow).not.toHaveBeenCalled()
  })
})
