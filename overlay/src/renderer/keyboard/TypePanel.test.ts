// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { agent, dwell, mounted, plan, resetPlatform, setSession, targetIds } from '../dock/test-platform'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

const keys = (...groups: string[]) => { for (const g of groups) act(() => { dwell(`key-${g}`) }) }
const field = () => document.querySelector('.kbd-field')!.textContent
const prediction = (word: string) => targetIds().find(id => id.startsWith('pred-') && id.endsWith(`-${word}`))!

beforeEach(() => resetPlatform({ mode: 'type' }))
afterEach(cleanup)

describe('Type mode: T9 → DONE → sentence cards → plan cards', () => {
  it('has the spec layout: 8 letter keys, ␣, ⌫, DONE, 123? and 5 prediction slots', () => {
    render(createElement(App))
    for (const g of ['ABC', 'DEF', 'GHI', 'JKL', 'MNO', 'PQRS', 'TUV', 'WXYZ', 'space', 'delete', 'done', 'page']) {
      expect(mounted(`key-${g}`), g).toBeTruthy()
    }
    expect(document.querySelectorAll('.kbd-predictions > *')).toHaveLength(5)
    expect(dwell('key-done')).toBe(false) // nothing typed yet
  })

  it('predicts locally, decodes on DONE and turns the chosen sentence into an intent', () => {
    render(createElement(App))
    keys('TUV', 'DEF', 'JKL', 'JKL')
    act(() => { dwell(prediction('tell')) })
    keys('MNO', 'MNO', 'MNO', 'space', 'JKL', 'ABC', 'TUV', 'DEF')
    expect(field()).toContain('tell mom')
    expect(agent.decode).not.toHaveBeenCalled() // zero tokens per keystroke

    act(() => { dwell('key-done') })
    expect(agent.decode).toHaveBeenCalledWith(['tell', 'mom'], ['JKL', 'ABC', 'TUV', 'DEF'])
    expect(document.querySelector('.waiting-panel')).toBeTruthy()

    act(() => setSession({ sentences: ['Tell Mom I’ll be late.', 'Tell Mom I’m running late.'] }))
    const cards = targetIds().filter(id => id.startsWith('sentence-'))
    expect(cards).toHaveLength(2)
    act(() => { dwell(cards[0]!) })
    expect(agent.submitIntent).toHaveBeenCalledWith('Tell Mom I’ll be late.')

    act(() => setSession({ sentences: null, list: { listId: 'P1', source: 'plans', items: [
      plan('p1', 'Text Mom: I’ll be late', { risky: true }), plan('other', 'Something else', { kind: 'other' })] } }))
    act(() => { dwell('plan-P1-p1') })
    expect(agent.selectPlan).toHaveBeenCalledWith('P1', 'p1')
  })

  it('"Something else" goes back to the keyboard with the text kept', () => {
    render(createElement(App))
    keys('MNO', 'MNO', 'MNO')
    act(() => { dwell(prediction('mom')) })
    act(() => { dwell('key-done') })
    act(() => setSession({ sentences: ['Mom.'] }))
    act(() => { dwell(targetIds().find(id => id.startsWith('sentence-'))!) })
    act(() => setSession({ list: { listId: 'P2', source: 'plans', items: [plan('other', 'Something else', { kind: 'other' })] } }))
    act(() => { dwell('plan-P2-other') })
    act(() => setSession({ list: null })) // the platform resets locally; nothing is sent for "other"
    expect(agent.selectPlan).toHaveBeenCalledWith('P2', 'other')
    expect(mounted('key-ABC')).toBeTruthy()
    expect(field()).toContain('mom')
  })

  it('a started task clears the typed text', () => {
    render(createElement(App))
    act(() => { dwell('key-ABC') })
    act(() => setSession({ task: { taskId: 't1', state: 'running', step: 0, maxSteps: 15, message: 'Starting…' } }))
    act(() => setSession({ task: null }))
    expect(document.querySelector('.kbd-placeholder')).toBeTruthy()
  })
})

describe('waiting_user and results in the dock', () => {
  const task = { taskId: 't1', state: 'waiting_user' as const, step: 4, maxSteps: 15, message: 'Which date?' }

  it('choice cards re-expand the dock, without tabs, with a Cancel card', () => {
    resetPlatform({ task, choice: { requestId: 'c1', taskId: 't1', question: 'Which date?',
      options: [{ id: 'nov13', label: 'Fri, Nov 13' }, { id: 'nov14', label: 'Sat, Nov 14' }] } })
    render(createElement(App))
    expect(mounted('tab-auto')).toBeNull()
    act(() => { dwell('choice-c1-nov14') })
    expect(agent.respondChoice).toHaveBeenCalledWith('nov14')
    act(() => { dwell('choice-c1-cancel') })
    expect(agent.respondChoice).toHaveBeenLastCalledWith(null)
  })

  it('a confirm covers everything except STOP', () => {
    resetPlatform({ task, confirm: { requestId: 'r1', taskId: 't1', action: 'buy', title: 'Buy 2 tickets?',
      details: ['Total: $398.00'], source: 'rule', demo_noop: true } })
    render(createElement(App))
    expect(document.querySelector('.confirm-screen')).toBeTruthy()
    expect(mounted('stop')!.getAttribute('aria-disabled')).toBeNull()
    expect(mounted('tab-auto')).toBeNull()
  })

  it('a failure shows the summary and recovery cards, including "Show me the screen"', () => {
    resetPlatform({ result: { taskId: 't1', ok: false, summary: 'I couldn’t find the Send button.', hasRecovery: true },
      list: { listId: 'R1', source: 'recovery', items: [plan('recovery:retry', 'Try again', { kind: 'recovery' }),
        plan('recovery:show_screen', 'Show me the screen', { kind: 'recovery' }), plan('recovery:cancel', 'Cancel', { kind: 'recovery' })] } })
    render(createElement(App))
    expect(document.querySelector('.summary-panel')!.textContent).toContain('I couldn’t find the Send button.')
    act(() => { dwell('recovery-R1-recovery:show_screen') })
    expect(agent.selectPlan).toHaveBeenCalledWith('R1', 'recovery:show_screen')
  })

  it('a finished task offers OK, which returns to the idle dock locally', () => {
    resetPlatform({ mode: 'auto', result: { taskId: 't2', ok: true, summary: 'Sent to Mom.', hasRecovery: false } })
    render(createElement(App))
    act(() => { dwell('result-ok-t2') })
    expect(agent.setMode).toHaveBeenCalledWith('auto')
    expect(agent.suggestNow).not.toHaveBeenCalled()
  })
})
