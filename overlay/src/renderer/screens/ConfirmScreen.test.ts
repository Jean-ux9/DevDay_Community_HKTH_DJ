// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { createElement } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionState } from '../platform'
import { agent, dwell, mounted, resetPlatform, targets } from '../dock/test-platform'
import { CONFIRM_TIMEOUT_MS, ConfirmScreen, detailLabel } from './ConfirmScreen'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

// Vitest blanks CSS imports (even ?raw), so read the stylesheet itself.
const css = readFileSync(join(__dirname, '../styles/overlay.css'), 'utf8')
type Confirm = NonNullable<SessionState['confirm']>
const confirm = (patch: Partial<Confirm> = {}): Confirm => ({
  requestId: 'req-1', taskId: 't1', action: 'send', title: 'Send message to Mom?',
  details: ['To: Mom (+1 555 0100)', 'Text: I’ll be late, sorry!'], source: 'rule', demo_noop: false, ...patch
})
/** Every declaration block whose selector list ends with `selector`. */
const rule = (selector: string) =>
  [...css.matchAll(new RegExp(`\\n${selector.replace('.', '\\.')} \\{([^}]*)\\}`, 'g'))].map(m => m[1]).join('')

beforeEach(() => { resetPlatform(); vi.useFakeTimers() })
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('Confirm screen (spec §6.2, §9)', () => {
  it('shows the title and every detail line', () => {
    render(createElement(ConfirmScreen, { confirm: confirm() }))
    expect(screen.getByText('Send message to Mom?')).toBeTruthy()
    expect([...document.querySelectorAll('.confirm-details li')].map(li => li.textContent))
      .toEqual(['To: Mom (+1 555 0100)', 'Text: I’ll be late, sorry!'])
  })

  it('CONFIRM is the long-dwell "confirm" target, bottom-left; CANCEL is top-right', () => {
    render(createElement(ConfirmScreen, { confirm: confirm() }))
    const yes = targets.get('confirm-yes-req-1')!
    // The platform applies max(1500, 1.5 × dwellMs) to variant "confirm"; no override here.
    expect(yes.variant).toBe('confirm')
    expect(yes.dwellMs).toBeUndefined()
    expect(mounted('confirm-yes-req-1')!.className).toContain('confirm-yes')
    expect(rule('.confirm-yes')).toMatch(/left:/)
    expect(rule('.confirm-yes')).toMatch(/bottom:/)
    expect(rule('.confirm-no')).toMatch(/top:/)
    expect(rule('.confirm-no')).toMatch(/right:/)
    expect(mounted('confirm-no-req-1')!.className).toContain('confirm-no')
  })

  it('CONFIRM answers true, CANCEL answers false', () => {
    render(createElement(ConfirmScreen, { confirm: confirm() }))
    act(() => { dwell('confirm-yes-req-1') })
    expect(agent.respondConfirm).toHaveBeenLastCalledWith(true)
    act(() => { dwell('confirm-no-req-1') })
    expect(agent.respondConfirm).toHaveBeenLastCalledWith(false)
  })

  it('cancels by itself after 60 s by sending false', () => {
    render(createElement(ConfirmScreen, { confirm: confirm() }))
    act(() => { vi.advanceTimersByTime(CONFIRM_TIMEOUT_MS - 1) })
    expect(agent.respondConfirm).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(1) })
    expect(agent.respondConfirm).toHaveBeenCalledTimes(1)
    expect(agent.respondConfirm).toHaveBeenCalledWith(false)
    expect(CONFIRM_TIMEOUT_MS).toBe(60_000)
  })

  it('a new confirm request restarts the 60 s clock; unmounting stops it', () => {
    const view = render(createElement(ConfirmScreen, { confirm: confirm() }))
    act(() => { vi.advanceTimersByTime(40_000) })
    view.rerender(createElement(ConfirmScreen, { confirm: confirm({ requestId: 'req-2' }) }))
    act(() => { vi.advanceTimersByTime(40_000) })
    expect(agent.respondConfirm).not.toHaveBeenCalled()
    view.unmount()
    act(() => { vi.advanceTimersByTime(60_000) })
    expect(agent.respondConfirm).not.toHaveBeenCalled()
  })

  it('shows the countdown', () => {
    render(createElement(ConfirmScreen, { confirm: confirm() }))
    act(() => { vi.advanceTimersByTime(5_000) })
    expect(screen.getByText('Cancels by itself in 55 s')).toBeTruthy()
  })

  it('shows "Demo: nothing is bought" only when demo_noop', () => {
    const view = render(createElement(ConfirmScreen, { confirm: confirm() }))
    expect(screen.queryByText('Demo: nothing is bought')).toBeNull()
    view.rerender(createElement(ConfirmScreen, { confirm: confirm({ action: 'buy', title: 'Buy 2 tickets?', demo_noop: true }) }))
    expect(screen.getByText('Demo: nothing is bought')).toBeTruthy()
    expect(mounted('confirm-yes-req-1')!.textContent).toContain('Buy')
  })

  it('structured email details: every line is shown exactly as sent, labels emphasised, line breaks kept', () => {
    const details = ['To: TeamMail (team@example.test)', 'Subject: Re: Friday 10:30', 'Body: Hi team,\n\nNote: room 4B.\n  — Sam']
    render(createElement(ConfirmScreen, { confirm: confirm({ title: 'Send this email?', details }) }))
    const items = [...document.querySelectorAll('.confirm-details li')] as HTMLElement[]
    expect(items.map(li => li.textContent)).toEqual(details)
    expect(items.map(li => li.querySelector('.confirm-detail-label')?.textContent)).toEqual(['To:', 'Subject:', 'Body:'])
    for (const li of items) expect(li.style.whiteSpace).toBe('pre-wrap')
    expect(document.querySelector('[role="alertdialog"]')!.getAttribute('aria-describedby')).toBe('confirm-details')
  })

  it('only a short leading word is a label; colons inside text are not', () => {
    expect(detailLabel('To: Sam')).toBe('To')
    expect(detailLabel('Recipient alias: TeamMessage')).toBe('Recipient alias')
    expect(detailLabel('Meet at 10:30 tomorrow')).toBeNull()
    expect(detailLabel('https://example.test/a:b')).toBeNull()
    expect(detailLabel(': nothing')).toBeNull()
    render(createElement(ConfirmScreen, { confirm: confirm({ details: ['Meet at 10:30 tomorrow'] }) }))
    const li = document.querySelector('.confirm-details li')!
    expect(li.textContent).toBe('Meet at 10:30 tomorrow')
    expect(li.querySelector('strong')).toBeNull()
  })

  it('a long message stays complete: smaller type, and the text ends above CONFIRM', () => {
    const body = 'Body: ' + 'All of this must be readable before sending. '.repeat(20)
    const view = render(createElement(ConfirmScreen, { confirm: confirm({ details: ['To: TeamMail', body] }) }))
    const items = [...document.querySelectorAll('.confirm-details li')] as HTMLElement[]
    expect(items[1]!.textContent).toBe(body)
    expect(items[0]!.style.fontSize).toBe('20px')
    const panel = document.querySelector('.confirm-body') as HTMLElement
    expect(panel.style.bottom).toBe('316px')
    expect(panel.style.overflowY).toBe('auto')
    view.rerender(createElement(ConfirmScreen, { confirm: confirm() }))
    expect((document.querySelector('.confirm-details li') as HTMLElement).style.fontSize).toBe('')
  })

  it('Cancel answers false and tells the owner it was not approved; the timeout does the same', () => {
    const onAnswer = vi.fn()
    render(createElement(ConfirmScreen, { confirm: confirm(), onAnswer }))
    act(() => { dwell('confirm-no-req-1') })
    expect(agent.respondConfirm).toHaveBeenCalledTimes(1)
    expect(agent.respondConfirm).toHaveBeenCalledWith(false)
    expect(onAnswer).toHaveBeenLastCalledWith(false, true)
    act(() => { vi.advanceTimersByTime(CONFIRM_TIMEOUT_MS) })
    expect(agent.respondConfirm).toHaveBeenLastCalledWith(false)
    expect(onAnswer).toHaveBeenLastCalledWith(false, true)
    expect(onAnswer).not.toHaveBeenCalledWith(true, expect.anything())
  })

  it('without an owner callback every answer still reaches the agent', () => {
    render(createElement(ConfirmScreen, { confirm: confirm() }))
    act(() => { dwell('confirm-no-req-1') })
    expect(agent.respondConfirm).toHaveBeenCalledWith(false)
  })

  it('CONFIRM reports whether the answer actually reached the agent', () => {
    const onAnswer = vi.fn()
    agent.respondConfirm.mockReturnValueOnce(false)
    render(createElement(ConfirmScreen, { confirm: confirm(), onAnswer }))
    act(() => { dwell('confirm-yes-req-1') })
    expect(onAnswer).toHaveBeenLastCalledWith(true, false)
  })
})
