import { describe, expect, it } from 'vitest'
import Ajv2020 from 'ajv/dist/2020'
import schema from '../../../../protocol/messages.schema.json'
import d1 from './fixtures/d1.json'
import d2 from './fixtures/d2.json'
import d3 from './fixtures/d3.json'
import d4 from './fixtures/d4.json'
import recovery from './fixtures/recovery.json'
import settings from './fixtures/settings.json'
import staleList from './fixtures/stale_list.json'
import stopDuringConfirm from './fixtures/stop_during_confirm.json'
import taskBusy from './fixtures/task_busy.json'
import type { RecordedFlow } from './test-utils'
import { makeMessage, messageErrors, parseIncoming } from './validate'

const flows = [d1, d2, d3, d4, recovery, settings, staleList, stopDuringConfirm, taskBusy] as unknown as RecordedFlow[]

describe('contract: frames recorded from the fake agent', () => {
  it('standalone validators agree with a fresh schema compilation on all recorded payloads', () => {
    const ajv = new Ajv2020({ allErrors: true, strict: false })
    ajv.addSchema(schema)
    for (const flow of flows) for (const frame of flow.frames) {
      const validate = ajv.getSchema(`${schema.$id}#/$defs/payload_${frame.msg.type}`)!
      expect(validate(frame.msg.payload)).toBe(true)
      const malformed = { ...frame.msg, payload: { unexpected: true } }
      expect(messageErrors(malformed, frame.dir === 'in' ? 'a2o' : 'o2a').length === 0).toBe(validate(malformed.payload))
    }
  })
  for (const flow of flows) {
    it(`${flow.flow}: every agent frame parses and every overlay frame validates`, () => {
      expect(flow.frames.length).toBeGreaterThan(5)
      for (const f of flow.frames) {
        if (f.dir === 'in') {
          const r = parseIncoming(JSON.stringify(f.msg))
          expect(r.ok, r.ok ? '' : `${f.msg.type}: ${r.error}`).toBe(true)
        } else {
          expect(messageErrors(f.msg, 'o2a'), String(f.msg.type)).toEqual([])
        }
      }
    })
  }
})

describe('parseIncoming', () => {
  const good = {
    v: 1,
    type: 'decode_result',
    id: '11111111-1111-4111-8111-111111111111',
    re: null,
    ts: 1,
    payload: { sentences: ['Tell Mom I will be late.'] }
  }

  it('accepts a valid message', () => {
    expect(parseIncoming(JSON.stringify(good))).toEqual({ ok: true, msg: good })
  })

  it.each([
    ['not JSON', '{nope'],
    ['wrong protocol version', JSON.stringify({ ...good, v: 2 })],
    ['missing envelope field', JSON.stringify({ ...good, ts: undefined })],
    ['non-uuid id', JSON.stringify({ ...good, id: 'abc' })],
    ['unknown type', JSON.stringify({ ...good, type: 'telepathy' })],
    ['overlay-to-agent type from the agent', JSON.stringify({ ...good, type: 'stop', payload: { reason: 'gaze' } })],
    ['payload with a wrong field', JSON.stringify({ ...good, payload: { sentences: 'nope' } })],
    ['payload with too many sentences', JSON.stringify({ ...good, payload: { sentences: ['a', 'b', 'c', 'd'] } })],
    ['extra envelope field', JSON.stringify({ ...good, extra: true })]
  ])('rejects %s', (_label, raw) => {
    const r = parseIncoming(raw)
    expect(r.ok).toBe(false)
  })
})

describe('makeMessage', () => {
  it('builds a valid envelope', () => {
    const m = makeMessage('mode_set', { mode: 'type' }, null, { now: () => 42, uuid: () => '22222222-2222-4222-8222-222222222222' })
    expect(m).toEqual({ v: 1, type: 'mode_set', id: '22222222-2222-4222-8222-222222222222', re: null, ts: 42, payload: { mode: 'type' } })
  })

  it('refuses to build an invalid payload', () => {
    expect(() => makeMessage('mode_set', { mode: 'sideways' } as never)).toThrow(/invalid mode_set/)
    expect(() => makeMessage('stop', { reason: 'whim' } as never)).toThrow(/invalid stop/)
  })
})
