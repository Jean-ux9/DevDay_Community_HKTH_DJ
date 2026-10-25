// @vitest-environment jsdom
// Structured actions end to end in the overlay (H4): confirm → progress → an honest result. Session
// states stand in for the agent's confirm_request / task_status / task_result messages.
import { createElement } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { SessionState } from './platform'
import { agent, dwell, mounted, resetPlatform, setSession } from './dock/test-platform'

vi.mock('./platform', async () => (await import('./dock/test-platform')).platformMock)

type Confirm = NonNullable<SessionState['confirm']>
const DETAILS = ['To: TeamMail (team@example.test)', 'Subject: Demo', 'Body: Hello from Gaze.\nSecond line.']
const confirm = (patch: Partial<Confirm> = {}): Confirm => ({
  requestId: 'req-1', taskId: 't1', action: 'send', title: 'Send this email?',
  details: DETAILS, source: 'rule', demo_noop: false, ...patch
})
const running = (message = 'Sending with Mail', step = 3) =>
  ({ taskId: 't1', state: 'running' as const, step, maxSteps: 15, message })
const result = (ok: boolean, summary: string, taskId = 't1') => ({ taskId, ok, summary, hasRecovery: false })

/** The agent asks; the overlay answers through `answerId`; the task then ends with `ok`. */
function flow(answerId: 'confirm-yes-req-1' | 'confirm-no-req-1', ok: boolean, summary: string, patch: Partial<Confirm> = {}) {
  render(createElement(App))
  act(() => setSession({ task: { ...running('Waiting for you'), state: 'waiting_user' }, confirm: confirm(patch) }))
  act(() => { dwell(answerId) })
  act(() => setSession({ confirm: null, task: running() }))
  act(() => setSession({ task: null, result: result(ok, summary) }))
}

beforeEach(() => { localStorage.clear(); resetPlatform() })
afterEach(cleanup)

describe('structured action flow', () => {
  it('the confirm screen shows recipient and content exactly, with Cancel and STOP both gaze targets', () => {
    render(createElement(App))
    act(() => setSession({ task: { ...running(), state: 'waiting_user' }, confirm: confirm() }))
    expect([...document.querySelectorAll('.confirm-details li')].map(li => li.textContent)).toEqual(DETAILS)
    expect(mounted('confirm-no-req-1')).toBeTruthy()
    expect(mounted('stop')).toBeTruthy()
    expect(mounted('stop')!.textContent).toContain('Stops the task')
    act(() => { dwell('stop') })
    expect(agent.stop).toHaveBeenCalledWith('gaze')
    expect(agent.respondConfirm).not.toHaveBeenCalled()
  })

  it('progress: while the action runs the pill shows the agent’s step message, and STOP stays', () => {
    render(createElement(App))
    act(() => setSession({ task: running('Opening https://example.test', 2) }))
    expect(screen.getByText('Opening https://example.test')).toBeTruthy()
    expect(screen.getByText('Step 2')).toBeTruthy()
    expect(mounted('stop')).toBeTruthy()
  })

  it('Cancel sends false and the result is the ordinary "Not done"', () => {
    flow('confirm-no-req-1', false, 'Cancelled. Nothing was sent.')
    expect(agent.respondConfirm).toHaveBeenCalledTimes(1)
    expect(agent.respondConfirm).toHaveBeenCalledWith(false)
    expect(screen.getByText('Not done')).toBeTruthy()
    expect(screen.queryByText('Not confirmed')).toBeNull()
  })

  it('approved and the app accepted it: no "Done" and no success glow, delivery not claimed', () => {
    flow('confirm-yes-req-1', true, 'Mail accepted the message.')
    expect(agent.respondConfirm).toHaveBeenCalledWith(true)
    expect(screen.queryByText('Done')).toBeNull()
    expect(document.querySelector('.summary-panel.is-done')).toBeNull()
    expect(screen.getByText('Handed to the app')).toBeTruthy()
    expect(screen.getByText('Mail accepted the message.')).toBeTruthy()
    expect(screen.getByText('The app accepted it. Delivery is not confirmed.')).toBeTruthy()
    act(() => { dwell('result-ok-t1') })
    expect(agent.setMode).toHaveBeenCalledWith('auto')
  })

  it('approved then failed or unknown: "Not confirmed", never "Not done"', () => {
    flow('confirm-yes-req-1', false, 'Mail did not answer in time; the message may have been sent.')
    expect(screen.queryByText('Not done')).toBeNull()
    expect(screen.queryByText('Done')).toBeNull()
    expect(screen.getByText('Not confirmed')).toBeTruthy()
    expect(screen.getByText('Mail did not answer in time; the message may have been sent.')).toBeTruthy()
    expect(screen.getByText('It may have gone through. Check before trying again.')).toBeTruthy()
  })

  it('approved then refused before submission: "Not sent", with nothing-was-sent wording', () => {
    flow('confirm-yes-req-1', false, 'Message was not submitted: Mail has no account with the sender address.')
    expect(screen.getByText('Not sent')).toBeTruthy()
    expect(screen.queryByText('Not confirmed')).toBeNull()
    expect(screen.queryByText('It may have gone through. Check before trying again.')).toBeNull()
  })

  it('a demo no-op stays the ordinary result: nothing was actually bought', () => {
    flow('confirm-yes-req-1', true, 'Demo: nothing was bought.', { action: 'buy', title: 'Buy 2 tickets?', demo_noop: true })
    expect(screen.getByText('Done')).toBeTruthy()
    expect(screen.queryByText('Handed to the app')).toBeNull()
  })

  it('the approval belongs to its task: the next task’s result is ordinary again', () => {
    flow('confirm-yes-req-1', true, 'Mail accepted the message.')
    act(() => setSession({ result: null }))
    act(() => setSession({ task: { ...running(), taskId: 't2' } }))
    act(() => setSession({ task: null, result: result(true, 'Opened Safari.', 't2') }))
    expect(screen.getByText('Done')).toBeTruthy()
    expect(screen.queryByText('Handed to the app')).toBeNull()
  })

  it('a task error stays visible in plain words on the status line', () => {
    render(createElement(App))
    act(() => setSession({ lastError: { code: 'internal', message: 'Mail is not set up on this Mac.', re: null } }))
    expect(screen.getByText('Mail is not set up on this Mac.')).toBeTruthy()
  })
})
