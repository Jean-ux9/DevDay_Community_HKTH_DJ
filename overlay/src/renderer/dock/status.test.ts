import { describe, expect, it } from 'vitest'
import { baseSession } from './test-platform'
import { deriveStatus } from './status'

const task = { taskId: 't1', state: 'running' as const, step: 4, maxSteps: 15, message: 'Typing…' }

describe('status line', () => {
  it('connection states', () => {
    expect(deriveStatus(baseSession({ connection: 'connecting', ready: false }))).toEqual({ kind: 'connecting', text: 'Connecting…' })
    expect(deriveStatus(baseSession({ connection: 'reconnecting', ready: false })).text).toBe('Reconnecting…')
    expect(deriveStatus(baseSession({ connection: 'error', ready: false, closeCode: 4401 })).kind).toBe('error')
    expect(deriveStatus(baseSession({ connection: 'open', ready: false })).kind).toBe('connecting')
    expect(deriveStatus(baseSession())).toEqual({ kind: 'connected', text: 'Ready' })
  })

  it('thinking while the agent prepares suggestions, sentences or plans', () => {
    expect(deriveStatus(baseSession({ suggestPending: true })).kind).toBe('thinking')
    expect(deriveStatus(baseSession(), 'decode').kind).toBe('thinking')
    expect(deriveStatus(baseSession(), 'plans').text).toBe('Thinking…')
  })

  it('acting with the step count, waiting on choices and confirms, stopping', () => {
    expect(deriveStatus(baseSession({ task }))).toEqual({ kind: 'acting', text: 'Acting · step 4 of 15' })
    expect(deriveStatus(baseSession({ pendingSelect: 'm1' })).text).toBe('Starting…')
    expect(deriveStatus(baseSession({ task: { ...task, state: 'waiting_user' } })).kind).toBe('waiting')
    const confirm = { requestId: 'r', taskId: 't1', action: 'send' as const, title: 'Send?', details: [], source: 'rule' as const, demo_noop: false }
    expect(deriveStatus(baseSession({ task, confirm })).text).toBe('Waiting for you to confirm')
    expect(deriveStatus(baseSession({ task, stopping: true })).text).toBe('Stopping…')
  })

  it('shows real errors, but not the ones that only re-sync the dock', () => {
    expect(deriveStatus(baseSession({ lastError: { code: 'llm_failed', message: 'The model did not answer', re: null } })))
      .toEqual({ kind: 'error', text: 'The model did not answer' })
    expect(deriveStatus(baseSession({ lastError: { code: 'stale_list', message: 'old list', re: null } })).kind).toBe('connected')
  })
})
