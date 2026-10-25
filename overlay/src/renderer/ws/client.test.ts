import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AGENT_EXITED_CLOSE as MAIN_AGENT_EXITED_CLOSE } from '../../main/transport'
import { AGENT_EXITED_CLOSE, BACKOFF_MAX_MS, BACKOFF_MIN_MS, FATAL_CLOSE_CODES, SUGGEST_GAP_MS, SUGGEST_TIMEOUT_MESSAGE,
  SUGGEST_TIMEOUT_MS } from './client'
import d1 from './fixtures/d1.json'
import d2 from './fixtures/d2.json'
import d4 from './fixtures/d4.json'
import recovery from './fixtures/recovery.json'
import staleList from './fixtures/stale_list.json'
import stopDuringConfirm from './fixtures/stop_during_confirm.json'
import taskBusy from './fixtures/task_busy.json'
import { type RecordedFlow, connect, helloAck, makeRig, open, replay } from './test-utils'

const flow = (f: unknown) => f as RecordedFlow
const types = (rig: ReturnType<typeof makeRig>) => rig.socket().sent.map((m) => m.type)

describe('connection', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('sends hello first on connect, then mode_set with the last mode after hello_ack', () => {
    const rig = makeRig('type')
    open(rig)
    expect(types(rig)).toEqual(['hello'])
    expect(rig.socket().sent[0]!.payload).toEqual({ client: 'overlay', version: '0.1.0' })
    rig.socket().deliver(helloAck(rig.socket().sent[0]!.id))
    expect(types(rig)).toEqual(['hello', 'mode_set'])
    expect(rig.socket().sent[1]!.payload).toEqual({ mode: 'type' })
  })

  it('refuses to send before the socket is open', () => {
    const rig = makeRig()
    rig.client.start()
    expect(rig.client.send('stop', { reason: 'user' })).toBeNull()
    expect(rig.client.sendStop('user')).toBe(false)
  })

  it('reconnects with backoff 250 ms → 4 s and resets it after a hello_ack', () => {
    const rig = makeRig()
    rig.client.start()
    const expected = [250, 500, 1000, 2000, 4000, 4000]
    expect(expected[0]).toBe(BACKOFF_MIN_MS)
    expect(expected.at(-1)).toBe(BACKOFF_MAX_MS)
    for (const [i, delay] of expected.entries()) {
      expect(rig.sockets).toHaveLength(i + 1)
      rig.socket().drop()
      expect(rig.client.getState().connection).toBe('reconnecting')
      vi.advanceTimersByTime(delay - 1)
      expect(rig.sockets, `no retry before ${delay} ms`).toHaveLength(i + 1)
      vi.advanceTimersByTime(1)
      expect(rig.sockets, `retry at ${delay} ms`).toHaveLength(i + 2)
    }
    // A completed handshake resets the delay.
    rig.socket().open()
    rig.socket().deliver(helloAck(rig.socket().sent[0]!.id))
    const n = rig.sockets.length
    rig.socket().drop()
    vi.advanceTimersByTime(BACKOFF_MIN_MS)
    expect(rig.sockets).toHaveLength(n + 1)
  })

  it.each([4401, 4400])('close code %i is an error state, not a retry loop', (code) => {
    const rig = makeRig()
    rig.client.start()
    rig.socket().drop(code)
    vi.advanceTimersByTime(60_000)
    expect(rig.sockets).toHaveLength(1)
    expect(rig.client.getState().connection).toBe('error')
    expect(rig.client.getState().closeCode).toBe(code)
  })

  it('stop() closes the socket and does not reconnect', () => {
    const rig = makeRig()
    connect(rig)
    const socket = rig.socket()
    rig.client.stop()
    expect(socket.closed).toBe(true)
    vi.advanceTimersByTime(60_000)
    expect(rig.sockets).toHaveLength(1)
  })
})

describe('validation', () => {
  it('rejects an invalid message: state untouched, diagnostic recorded, no crash', () => {
    const rig = makeRig()
    connect(rig)
    const before = rig.client.getState()
    rig.socket().deliver('{not json')
    rig.socket().deliver({ v: 1, type: 'plans', id: 'x', re: null, ts: 1, payload: {} })
    rig.socket().deliver({ v: 1, type: 'telepathy', id: '33333333-3333-4333-8333-333333333333', re: null, ts: 1, payload: {} })
    expect(rig.client.getState()).toBe(before)
    expect(rig.diagnostics.map((d) => d.kind)).toEqual(['invalid', 'invalid', 'invalid'])
  })
})

describe('hello_ack resets the UI to idle', () => {
  it('mid-task: pill, choice and confirm are gone; the mode survives; mode_set is re-sent', () => {
    vi.useFakeTimers()
    const rig = makeRig()
    open(rig)
    rig.client.setMode('type') // not ready yet: only remembered
    replay(rig, flow(d4), (f) => f.dir === 'in' && f.msg.type === 'confirm_request')
    const mid = rig.client.getState()
    expect(mid.task).not.toBeNull()
    expect(mid.confirm?.demo_noop).toBe(true)

    rig.socket().drop()
    expect(rig.client.getState().connection).toBe('reconnecting')
    vi.advanceTimersByTime(BACKOFF_MIN_MS)
    rig.socket().open()
    rig.socket().deliver(helloAck(rig.socket().sent[0]!.id))

    const s = rig.client.getState()
    expect(s).toMatchObject({ connection: 'open', ready: true, mode: 'type', task: null, choice: null, confirm: null, result: null, list: null, pendingSelect: null })
    expect(types(rig)).toEqual(['hello', 'mode_set'])
    expect(rig.socket().sent[1]!.payload).toEqual({ mode: 'type' })
    vi.useRealTimers()
  })

  it('answers for the old task are refused after the reset', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d4), (f) => f.dir === 'in' && f.msg.type === 'confirm_request')
    rig.socket().deliver(helloAck(rig.socket().sent[0]!.id, '44444444-4444-4444-8444-444444444444'))
    const sentBefore = rig.socket().sent.length
    expect(rig.client.respondConfirm(true)).toBe(false)
    expect(rig.socket().sent).toHaveLength(sentBefore)
  })
})

describe('task lifecycle (§4.4), replaying recorded D1', () => {
  it('collapses to the pill only on the first running status, not when plan_select is sent', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1), (f) => f.dir === 'in' && f.msg.type === 'plans')
    const list = rig.client.getState().list!
    expect(list.source).toBe('plans')
    expect(rig.client.selectPlan(list.listId, list.items[0]!.id)).toBe(true)
    expect(types(rig).at(-1)).toBe('plan_select')
    expect(rig.client.getState().task).toBeNull() // dock still expanded
    expect(rig.client.getState().pendingSelect).not.toBeNull()
  })

  it('runs the whole flow: pill → confirm → done → result, with no frame dropped', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1))
    const s = rig.client.getState()
    expect(s.task).toBeNull()
    expect(s.confirm).toBeNull()
    expect(s.result).toMatchObject({ ok: true })
    expect(rig.diagnostics.filter((d) => d.kind === 'dropped')).toEqual([])
  })

  it('answers a confirm with the request id as `re` and the active task id', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1), (f) => f.dir === 'in' && f.msg.type === 'confirm_request')
    const req = rig.client.getState().confirm!
    expect(rig.client.respondConfirm(true)).toBe(true)
    const sent = rig.socket().sent.at(-1)!
    expect(sent).toMatchObject({ type: 'confirm_response', re: req.requestId, payload: { task_id: req.taskId, confirmed: true } })
    expect(rig.client.getState().confirm).toBeNull() // a second dwell can't answer twice
    expect(rig.client.respondConfirm(false)).toBe(false)
  })

  it('answers a choice, and null cancels', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d4), (f) => f.dir === 'in' && f.msg.type === 'choice_request')
    const req = rig.client.getState().choice!
    expect(req.options.length).toBeGreaterThanOrEqual(2)
    expect(rig.client.respondChoice(null)).toBe(true)
    expect(rig.socket().sent.at(-1)).toMatchObject({ type: 'choice_response', re: req.requestId, payload: { task_id: req.taskId, choice_id: null } })
  })

  it('ignores every message of a dead task_id (replayed after the task ended)', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1))
    const done = rig.client.getState()
    const dead = flow(d1).frames.filter((f) => f.dir === 'in' && 'task_id' in f.msg.payload)
    expect(dead.length).toBeGreaterThan(4)
    for (const f of dead) rig.socket().deliver(f.msg)
    expect(rig.client.getState()).toBe(done)
    expect(rig.diagnostics.filter((d) => d.kind === 'dropped')).toHaveLength(dead.length)
  })

  it("ignores another task's messages while a task is active", () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1), (f) => f.dir === 'in' && f.msg.type === 'confirm_request')
    const live = rig.client.getState()
    const foreign = flow(d4).frames.filter((f) => f.dir === 'in' && 'task_id' in f.msg.payload)
    for (const f of foreign) rig.socket().deliver(f.msg)
    expect(rig.client.getState()).toBe(live)
  })

  it('does not start a task from a running status it did not ask for', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1), (f) => f.dir === 'in' && f.msg.type === 'plans')
    const running = flow(d1).frames.find((f) => f.dir === 'in' && f.msg.type === 'task_status')!
    rig.socket().deliver(running.msg) // nobody sent a plan_select
    expect(rig.client.getState().task).toBeNull()
  })

  it('after a terminal status only the task_result is accepted', () => {
    const rig = makeRig()
    open(rig)
    const frames = flow(stopDuringConfirm).frames
    const stopped = frames.findIndex((f) => f.dir === 'in' && f.msg.type === 'task_status' && f.msg.payload.state === 'stopped')
    replay(rig, flow(stopDuringConfirm), (_f, i) => i === stopped)
    const afterStop = rig.client.getState()
    expect(afterStop.task?.state).toBe('stopped')
    const late = frames.find((f) => f.dir === 'in' && f.msg.type === 'confirm_request')!
    rig.socket().deliver({ ...late.msg, id: '55555555-5555-4555-8555-555555555555' })
    expect(rig.client.getState()).toBe(afterStop)
    // A second status for the same task (e.g. a stray "running" after "stopped") is dead too.
    const running = frames.find((f) => f.dir === 'in' && f.msg.type === 'task_status' && f.msg.payload.state === 'running')!
    rig.socket().deliver({ ...running.msg, id: '66666666-6666-4666-8666-666666666666', re: null })
    expect(rig.client.getState()).toBe(afterStop)
  })
})

describe('recorded stop_during_confirm', () => {
  it('stop wins: the late confirm is refused locally and the agent answers no_task', () => {
    const rig = makeRig()
    open(rig)
    const frames = flow(stopDuringConfirm).frames
    const stopSent = frames.findIndex((f) => f.dir === 'out' && f.msg.type === 'stop')
    replay(rig, flow(stopDuringConfirm), (_f, i) => i === stopSent + 2) // stopped status + task_result delivered
    const s = rig.client.getState()
    expect(s).toMatchObject({ task: null, confirm: null, result: { ok: false } })
    const sentBefore = rig.socket().sent.length
    expect(rig.client.respondConfirm(true)).toBe(false)
    expect(rig.socket().sent).toHaveLength(sentBefore)
  })

  it('replays the whole recorded flow, including the agent’s no_task error for the late confirm', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(stopDuringConfirm))
    const s = rig.client.getState()
    expect(s.lastError?.code).toBe('no_task')
    expect(s.task).toBeNull()
    expect(s.result?.ok).toBe(false)
  })
})

describe('lists (§4.4): only the most recent list is selectable', () => {
  it('refuses a superseded list_id locally and sends nothing', () => {
    const rig = makeRig()
    open(rig)
    const frames = flow(staleList).frames
    const plans = frames.filter((f) => f.dir === 'in' && f.msg.type === 'plans')
    expect(plans).toHaveLength(2)
    const secondPlans = frames.indexOf(plans[1]!)
    replay(rig, flow(staleList), (_f, i) => i === secondPlans)
    const oldList = plans[0]!.msg.payload.list_id as string
    const oldPlan = (plans[0]!.msg.payload.items as { id: string }[])[0]!.id
    const current = rig.client.getState().list!
    expect(current.listId).toBe(plans[1]!.msg.payload.list_id)
    const sentBefore = rig.socket().sent.length
    expect(rig.client.selectPlan(oldList, oldPlan)).toBe(false)
    expect(rig.socket().sent).toHaveLength(sentBefore)
    expect(rig.client.selectPlan(current.listId, 'no-such-plan')).toBe(false)
    expect(rig.socket().sent).toHaveLength(sentBefore)
  })

  it('a stale_list error (the race the agent catches) refreshes the dock instead of crashing', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(staleList)) // includes the racing plan_select and the agent's error
    const s = rig.client.getState()
    expect(s.lastError?.code).toBe('stale_list')
    expect(s.refreshTick).toBe(1)
    expect(s.pendingSelect).toBeNull()
    expect(s.task).toBeNull()
    expect(s.list?.source).toBe('plans') // the current list is still there to select from
  })

  it('task_busy also refreshes without disturbing the running task', () => {
    const rig = makeRig()
    open(rig)
    const frames = flow(taskBusy).frames
    const busy = frames.findIndex((f) => f.dir === 'in' && f.msg.type === 'error')
    replay(rig, flow(taskBusy), (_f, i) => i === busy)
    const s = rig.client.getState()
    expect(s.lastError?.code).toBe('task_busy')
    expect(s.refreshTick).toBe(1)
    expect(s.task?.state).toBe('running')
  })

  it('a new list replaces the old one, whatever its source', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d2), (f) => f.dir === 'in' && f.msg.type === 'suggestions')
    expect(rig.client.getState().list?.source).toBe('suggestions')
    const plans = flow(d1).frames.find((f) => f.dir === 'in' && f.msg.type === 'plans')!
    rig.socket().deliver(plans.msg)
    expect(rig.client.getState().list).toMatchObject({ source: 'plans', listId: plans.msg.payload.list_id })
  })

  it('never sends plan_select for "Something else"', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1), (f) => f.dir === 'in' && f.msg.type === 'plans')
    const list = rig.client.getState().list!
    const other = list.items.at(-1)!
    expect(other.id).toBe('other')
    const sentBefore = rig.socket().sent.length
    expect(rig.client.selectPlan(list.listId, other.id)).toBe(false)
    expect(rig.socket().sent).toHaveLength(sentBefore)
    rig.client.resetLocal() // what the UI does instead: back to the idle dock
    expect(rig.client.getState().list).toBeNull()
  })
})

describe('Auto suggestions are only accepted while the Auto dock is showing', () => {
  const suggestion = () => flow(d2).frames.find((f) => f.dir === 'in' && f.msg.type === 'suggestions')!.msg

  it('accepts them in auto mode', () => {
    const rig = makeRig('auto')
    connect(rig)
    rig.socket().deliver(suggestion())
    expect(rig.client.getState().list?.source).toBe('suggestions')
  })

  it('drops them in type mode', () => {
    const rig = makeRig('type')
    connect(rig)
    rig.socket().deliver(suggestion())
    expect(rig.client.getState().list).toBeNull()
  })

  it('drops them while a task runs', () => {
    const rig = makeRig('auto')
    open(rig)
    replay(rig, flow(d1), (f) => f.dir === 'in' && f.msg.type === 'confirm_request')
    const before = rig.client.getState()
    rig.socket().deliver(suggestion())
    expect(rig.client.getState()).toBe(before)
  })

  it('drops them while a result is on screen', () => {
    const rig = makeRig('auto')
    open(rig)
    replay(rig, flow(recovery), (f) => f.dir === 'in' && f.msg.type === 'task_result')
    const before = rig.client.getState()
    expect(before.result).not.toBeNull()
    rig.socket().deliver(suggestion())
    expect(rig.client.getState()).toBe(before)
  })
})

describe('recovery (recorded)', () => {
  it('failure → recovery cards; Cancel is local; Show me the screen runs a task and returns a summary', () => {
    const rig = makeRig()
    open(rig)
    const frames = flow(recovery).frames
    const firstResult = frames.findIndex((f) => f.dir === 'in' && f.msg.type === 'task_result')
    const cursor = replay(rig, flow(recovery), (_f, i) => i === firstResult)
    let s = rig.client.getState()
    expect(s.result).toMatchObject({ ok: false, hasRecovery: true })
    expect(s.list?.source).toBe('recovery')
    expect(s.list?.items.map((p) => p.id)).toEqual(['recovery:retry', 'recovery:show_screen', 'recovery:cancel'])

    const sentBefore = rig.socket().sent.length
    expect(rig.client.selectPlan(s.list!.listId, 'recovery:cancel')).toBe(false)
    expect(rig.socket().sent).toHaveLength(sentBefore)

    replay(rig, flow(recovery), undefined, cursor) // the rest: show_screen task, then retry
    s = rig.client.getState()
    expect(s.result?.ok).toBe(true)
    expect(rig.diagnostics.filter((d) => d.kind === 'dropped')).toEqual([])
    const lists = frames.filter((f) => f.dir === 'in' && f.msg.type === 'task_result')
    expect(lists).toHaveLength(3) // failed, show_screen, retry
  })
})

describe('Suggest now and stop races', () => {
  it('does not suggest at launch; sends auto_refresh once and clears the spinner on suggestions', () => {
    const rig = makeRig()
    connect(rig)
    expect(types(rig)).not.toContain('auto_refresh')
    expect(rig.client.suggestNow()).toBe(true)
    expect(rig.client.getState().suggestPending).toBe(true)
    expect(rig.client.suggestNow()).toBe(false)
    const suggestion = (d2 as unknown as RecordedFlow).frames.find(f => f.msg.type === 'suggestions')!.msg
    rig.socket().deliver(suggestion)
    expect(rig.client.getState().suggestPending).toBe(false)
    expect(rig.client.getState().list?.source).toBe('suggestions')
    expect(types(rig).filter(t => t === 'auto_refresh')).toHaveLength(1)
  })
  it('clears suggestPending on its error, mode change or disconnect', () => {
    const rig = makeRig(); connect(rig)
    rig.client.suggestNow()
    const id = rig.socket().sent.at(-1)!.id
    rig.socket().deliver({ v: 1, type: 'error', id: crypto.randomUUID(), re: id, ts: 1, payload: { code: 'llm_failed', message: 'Fake failure' } })
    expect(rig.client.getState().suggestPending).toBe(false)
    rig.client.suggestNow(); rig.client.setMode('type')
    expect(rig.client.getState().suggestPending).toBe(false)
    expect(rig.client.suggestNow()).toBe(false)
    rig.client.setMode('auto'); rig.client.suggestNow(); rig.client.stop()
  })
  it('a STOP while idle does not swallow the next task\'s confirm (Auto suggestion path)', () => {
    const rig = makeRig(); open(rig)
    const cursor = replay(rig, flow(d2), f => f.dir === 'in' && f.msg.type === 'suggestions')
    expect(rig.client.sendStop('hotkey')).toBe(true) // nothing running: a no-op for the agent
    replay(rig, flow(d2), f => f.dir === 'in' && f.msg.type === 'confirm_request', cursor)
    expect(rig.client.getState().stopping).toBe(false)
    expect(rig.client.getState().confirm).not.toBeNull()
  })
  it('refuses CONFIRM immediately after STOP even before the server answers', () => {
    const rig = makeRig(); open(rig)
    replay(rig, flow(d4), f => f.dir === 'in' && f.msg.type === 'confirm_request')
    expect(rig.client.getState().confirm).not.toBeNull()
    rig.client.sendStop('gaze')
    expect(rig.client.respondConfirm(true)).toBe(false)
    expect(rig.client.getState().confirm).toBeNull()
  })
})

describe('live-agent failures stay visible (fake sockets, fake timers)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())
  const suggestion = () => (d2 as unknown as RecordedFlow).frames.find(f => f.msg.type === 'suggestions')!.msg
  const refreshes = (rig: ReturnType<typeof makeRig>) => types(rig).filter(t => t === 'auto_refresh').length

  it('uses the same close code as Electron main', () => {
    expect(AGENT_EXITED_CLOSE).toBe(MAIN_AGENT_EXITED_CLOSE)
    expect(FATAL_CLOSE_CODES.has(AGENT_EXITED_CLOSE)).toBe(true)
  })

  it('a gone agent is an error state, not a retry loop, and its task view ends', () => {
    const rig = makeRig()
    open(rig)
    replay(rig, flow(d1), (f) => f.dir === 'in' && f.msg.type === 'task_status')
    expect(rig.client.getState().task).not.toBeNull()
    rig.socket().drop(AGENT_EXITED_CLOSE)
    vi.advanceTimersByTime(60_000)
    expect(rig.sockets).toHaveLength(1)
    expect(rig.client.getState()).toMatchObject({ connection: 'error', closeCode: AGENT_EXITED_CLOSE, ready: false, task: null, pendingSelect: null, confirm: null, choice: null })
  })

  it('an unanswered Suggest now stops spinning after SUGGEST_TIMEOUT_MS and says so', () => {
    const rig = makeRig(); connect(rig)
    expect(rig.client.suggestNow()).toBe(true)
    const id = rig.socket().sent.at(-1)!.id
    vi.advanceTimersByTime(SUGGEST_TIMEOUT_MS - 1)
    expect(rig.client.getState().suggestPending).toBe(true)
    vi.advanceTimersByTime(1)
    expect(rig.client.getState()).toMatchObject({ suggestPending: false, suggestRequest: null,
      lastError: { code: 'suggest_timeout', message: SUGGEST_TIMEOUT_MESSAGE, re: id } })
    // A late answer is still shown (§4.4 accepts suggestions while the Auto dock shows); retrying clears the error.
    rig.socket().deliver(suggestion())
    expect(rig.client.getState().list?.source).toBe('suggestions')
    expect(rig.client.suggestNow()).toBe(true)
    expect(rig.client.getState().lastError).toBeNull()
  })

  it('an answered or abandoned refresh never times out later', () => {
    const rig = makeRig(); connect(rig)
    rig.client.suggestNow()
    rig.socket().deliver(suggestion())
    vi.advanceTimersByTime(SUGGEST_TIMEOUT_MS * 2)
    expect(rig.client.getState().lastError).toBeNull()
    vi.advanceTimersByTime(SUGGEST_GAP_MS)
    rig.client.suggestNow(); rig.client.setMode('type')
    vi.advanceTimersByTime(SUGGEST_TIMEOUT_MS * 2)
    expect(rig.client.getState()).toMatchObject({ suggestPending: false, lastError: null })
  })

  it('a refresh too soon after the last one waits out the agent gap instead of being dropped unanswered', () => {
    const rig = makeRig(); connect(rig)
    rig.client.suggestNow()
    rig.socket().deliver(suggestion())
    vi.advanceTimersByTime(1000)
    expect(rig.client.suggestNow()).toBe(true)
    expect(rig.client.getState().suggestPending).toBe(true) // the spinner shows at once
    expect(refreshes(rig)).toBe(1)
    vi.advanceTimersByTime(SUGGEST_GAP_MS - 1000 - 1)
    expect(refreshes(rig)).toBe(1)
    vi.advanceTimersByTime(1)
    expect(refreshes(rig)).toBe(2)
    const id = rig.socket().sent.at(-1)!.id
    expect(rig.client.getState().suggestRequest).toBe(id) // its error reply still clears the spinner
    rig.socket().deliver({ v: 1, type: 'error', id: crypto.randomUUID(), re: id, ts: 1, payload: { code: 'llm_failed', message: 'The model request failed' } })
    expect(rig.client.getState()).toMatchObject({ suggestPending: false, lastError: { code: 'llm_failed' } })
  })

  it('a waiting refresh is cancelled by a mode switch or a disconnect', () => {
    const rig = makeRig(); connect(rig)
    rig.client.suggestNow()
    rig.socket().deliver(suggestion())
    rig.client.suggestNow(); rig.client.setMode('type'); rig.client.setMode('auto')
    expect(rig.client.getState().suggestPending).toBe(false)
    expect(rig.client.suggestNow()).toBe(true) // still inside the gap: waiting again
    rig.socket().drop()
    vi.advanceTimersByTime(SUGGEST_GAP_MS)
    expect(rig.sockets.flatMap(s => s.sent).filter(m => m.type === 'auto_refresh')).toHaveLength(1)
    expect(rig.client.getState().suggestPending).toBe(false)
  })
})
