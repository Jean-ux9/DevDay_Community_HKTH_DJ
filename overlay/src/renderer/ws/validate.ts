// Schema validation for every frame (spec §4.1). The schema file is the single source of truth.
import type { ValidateFunction } from 'ajv/dist/2020'
import * as validators from './validators.gen'
import schema from '../../../../protocol/messages.schema.json'
import type { AgentToOverlay, Message, MessageType, OverlayToAgent, PayloadMap } from './protocol.gen'

const DIRECTIONS = schema['x-messages'] as Record<string, 'o2a' | 'a2o'>
export const PROTOCOL_VERSION: number = schema['x-protocol-version']

// Standalone validators compile in Node during codegen, never via new Function in the renderer.
const validatorFor = (def: string): ValidateFunction => {
  const fn = validators[def as keyof typeof validators] as unknown as ValidateFunction | undefined
  if (!fn) throw new Error(`protocol schema has no $defs/${def}`)
  return fn
}

const envelopeValidator = validatorFor('Envelope')
const payloadValidators = new Map<string, ValidateFunction>(
  Object.keys(DIRECTIONS).map((type) => [type, validatorFor(`payload_${type}`)])
)

const describeErrors = (fn: ValidateFunction): string =>
  (fn.errors ?? []).map((e) => `${e.instancePath || '<root>'} ${e.message}`).join('; ')

/** Errors for a message in the given direction; empty when it is valid. */
export function messageErrors(msg: unknown, direction: 'o2a' | 'a2o'): string[] {
  if (!envelopeValidator(msg)) return [`envelope: ${describeErrors(envelopeValidator)}`]
  const { type, payload } = msg as { type: string; payload: unknown }
  if (!(type in DIRECTIONS)) return [`unknown message type ${JSON.stringify(type)}`]
  if (DIRECTIONS[type] !== direction) return [`${type} is ${DIRECTIONS[type]}, not allowed as ${direction}`]
  const validate = payloadValidators.get(type)!
  return validate(payload) ? [] : [`payload: ${describeErrors(validate)}`]
}

export type ParseResult = { ok: true; msg: AgentToOverlay } | { ok: false; error: string }

/** Decodes and validates an incoming (agent → overlay) frame. */
export function parseIncoming(raw: unknown): ParseResult {
  let value: unknown
  try {
    value = typeof raw === 'string' ? JSON.parse(raw) : raw
  } catch (e) {
    return { ok: false, error: `not JSON: ${(e as Error).message}` }
  }
  const errors = messageErrors(value, 'a2o')
  return errors.length ? { ok: false, error: errors.join('; ') } : { ok: true, msg: value as AgentToOverlay }
}

export type OverlayMessageType = OverlayToAgent['type']

/** Builds an outgoing envelope and refuses to return one that would not validate. */
export function makeMessage<T extends OverlayMessageType>(
  type: T,
  payload: PayloadMap[T],
  re: string | null = null,
  clock: { now(): number; uuid(): string } = { now: () => Date.now(), uuid: () => crypto.randomUUID() }
): Message<T> {
  const msg = { v: 1 as const, type, id: clock.uuid(), re, ts: clock.now(), payload } as unknown as Message<T>
  const errors = messageErrors(msg, 'o2a')
  if (errors.length) throw new Error(`refusing to send invalid ${type}: ${errors.join('; ')}`)
  return msg
}

export type { MessageType }
