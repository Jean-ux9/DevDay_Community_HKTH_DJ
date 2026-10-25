// WebSocket client for the agent (spec §4): reconnect with backoff, schema validation of every
// frame, and the client side of the §4.4 lifecycle rules (via the pure reducer in session.ts).
import { APP_VERSION } from '../../shared/app'
import type { Message, PayloadMap } from './protocol.gen'
import {
  type Action,
  type Mode,
  type SessionState,
  initialSession,
  isSelectable,
  reduce
} from './session'
import { type OverlayMessageType, makeMessage, parseIncoming } from './validate'

/** The subset of the browser WebSocket the client uses; tests supply a fake. */
export interface SocketLike {
  onopen: ((ev: unknown) => void) | null
  onmessage: ((ev: { data: unknown }) => void) | null
  onclose: ((ev: { code: number; reason?: string }) => void) | null
  onerror: ((ev: unknown) => void) | null
  send(data: string): void
  close(code?: number, reason?: string): void
}

export type SocketFactory = (url: string) => SocketLike

export const BACKOFF_MIN_MS = 250
export const BACKOFF_MAX_MS = 4000
/** Electron main closes with this once the agent process it spawned has exited (main/transport.ts). */
export const AGENT_EXITED_CLOSE = 4500
/**
 * Retrying can't help: the agent closes with 4401/4400 when the token or the protocol version is
 * wrong, and main reports a dead agent with AGENT_EXITED_CLOSE.
 */
export const FATAL_CLOSE_CODES: ReadonlySet<number> = new Set([4400, 4401, AGENT_EXITED_CLOSE])
/** The agent ignores an auto_refresh within 3 s of the last one it ran (§7), timed from its 1 s Auto tick. */
export const SUGGEST_GAP_MS = 4000
/**
 * The real agent can drop a refresh without any reply (a failed model call, a changed window), and the
 * protocol has no ack for it. Stop the spinner after this and say so, rather than "Thinking…" forever.
 */
export const SUGGEST_TIMEOUT_MS = 90_000
export const SUGGEST_TIMEOUT_MESSAGE = 'No suggestions arrived. Try again; if it keeps happening, check the agent terminal.'

export interface ClientOptions {
  url: string
  createSocket?: SocketFactory
  initialMode?: Mode
  /** Called with every frame that was dropped or invalid, for logs. */
  onDiagnostic?: (kind: 'invalid' | 'dropped', detail: string) => void
}

/** Plan ids that never go over the wire (spec §4.2, §8.4). */
const LOCAL_ONLY_PLANS: ReadonlySet<string> = new Set(['other', 'recovery:cancel'])

export type StopReason = 'gaze' | 'hotkey' | 'user'

export class GazeWsClient {
  private state: SessionState
  private socket: SocketLike | null = null
  private backoffMs = BACKOFF_MIN_MS
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private suggestTimer: ReturnType<typeof setTimeout> | null = null
  private lastSuggestAt = Number.NEGATIVE_INFINITY
  private stopped = true
  private readonly listeners = new Set<(s: SessionState) => void>()
  private readonly createSocket: SocketFactory

  constructor(private readonly options: ClientOptions) {
    this.state = initialSession(options.initialMode ?? 'auto')
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike)
  }

  getState(): SessionState {
    return this.state
  }

  subscribe(listener: (s: SessionState) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  start(): void {
    if (!this.stopped) return
    this.stopped = false
    this.connect()
  }

  stop(): void {
    this.stopped = true
    if (this.retryTimer) clearTimeout(this.retryTimer)
    this.retryTimer = null
    this.clearSuggestTimer()
    const socket = this.socket
    this.socket = null
    socket?.close()
  }

  // ---- sending ----

  /** Sends a message; returns it, or null when there is no open connection. */
  send<T extends OverlayMessageType>(type: T, payload: PayloadMap[T], re: string | null = null): Message<T> | null {
    if (!this.canSend(type)) return null
    return this.transmit(makeMessage(type, payload, re))
  }

  private canSend(type: OverlayMessageType): boolean {
    return !!this.socket && this.state.connection === 'open' && (this.state.ready || type === 'hello')
  }

  private transmit<T extends OverlayMessageType>(msg: Message<T>): Message<T> {
    if (msg.type === 'plan_select') this.dispatch({ type: 'pending_select', id: msg.id })
    if (msg.type === 'auto_refresh') {
      this.dispatch({ type: 'suggest', id: msg.id })
      this.lastSuggestAt = Date.now()
      this.armSuggestTimer(() => this.dispatch({ type: 'suggest_timeout', id: msg.id, message: SUGGEST_TIMEOUT_MESSAGE }), SUGGEST_TIMEOUT_MS)
    }
    this.socket!.send(JSON.stringify(msg))
    return msg
  }

  private armSuggestTimer(run: () => void, ms: number): void {
    this.clearSuggestTimer()
    this.suggestTimer = setTimeout(() => { this.suggestTimer = null; run() }, ms)
  }

  private clearSuggestTimer(): void {
    if (this.suggestTimer) clearTimeout(this.suggestTimer)
    this.suggestTimer = null
  }

  setMode(mode: Mode): void {
    this.dispatch({ type: 'mode', mode })
    if (this.state.ready) this.send('mode_set', { mode })
  }

  suggestNow(): boolean {
    if (this.state.suggestPending || this.state.mode !== 'auto' || this.state.task || this.state.pendingSelect) return false
    if (!this.canSend('auto_refresh')) return false
    this.resetLocal()
    const wait = this.lastSuggestAt + SUGGEST_GAP_MS - Date.now()
    if (wait <= 0) return this.send('auto_refresh', {}) !== null
    // Too soon for the agent, which would drop it unanswered: spin now, send once the gap has passed.
    const msg = makeMessage('auto_refresh', {})
    this.dispatch({ type: 'suggest', id: msg.id })
    this.armSuggestTimer(() => {
      if (this.state.suggestRequest === msg.id && this.canSend('auto_refresh')) this.transmit(msg)
    }, wait)
    return true
  }

  /**
   * plan_select for a card of the current list. Refuses a superseded list instead of sending it
   * (§4.4), and never sends for "Something else" or recovery:cancel: the UI handles those locally.
   */
  selectPlan(listId: string, planId: string): boolean {
    if (this.state.task || this.state.pendingSelect) return false
    if (!isSelectable(this.state, listId, planId)) return false
    if (LOCAL_ONLY_PLANS.has(planId)) return false
    return this.send('plan_select', { list_id: listId, plan_id: planId }) !== null
  }

  /** Answers the pending choice (`null` = cancel). */
  respondChoice(choiceId: string | null): boolean {
    if (this.state.stopping) return false
    const c = this.state.choice
    if (!c || !this.state.task || this.state.task.taskId !== c.taskId) return false
    const sent = this.send('choice_response', { task_id: c.taskId, choice_id: choiceId }, c.requestId)
    if (sent) this.dispatch({ type: 'answered', kind: 'choice' })
    return sent !== null
  }

  /** Answers the pending confirm (CONFIRM / CANCEL / the 60 s auto-cancel). */
  respondConfirm(confirmed: boolean): boolean {
    if (this.state.stopping) return false
    const c = this.state.confirm
    if (!c || !this.state.task || this.state.task.taskId !== c.taskId) return false
    const sent = this.send('confirm_response', { task_id: c.taskId, confirmed }, c.requestId)
    if (sent) this.dispatch({ type: 'answered', kind: 'confirm' })
    return sent !== null
  }

  /** STOP always goes out, even when we think we're idle: the agent treats it as a no-op then. */
  sendStop(reason: StopReason): boolean {
    const sent = this.send('stop', { reason }) !== null
    if (sent) this.noteStop()
    return sent
  }

  /** Main sent panic directly on this connection. Drop any late select/confirm. */
  noteStop(): void { this.dispatch({ type: 'stopping' }) }

  /** Back to the idle dock without a message ("Something else", recovery:cancel). */
  resetLocal(): void {
    this.dispatch({ type: 'local_reset' })
  }

  // ---- connection ----

  private connect(): void {
    if (this.stopped) return
    const socket = this.createSocket(this.options.url)
    this.socket = socket
    socket.onopen = () => {
      if (this.socket !== socket) return
      this.dispatch({ type: 'connection', connection: 'open' })
      // hello is always first on every (re)connect; mode_set follows the hello_ack (see onFrame).
      this.send('hello', { client: 'overlay', version: APP_VERSION })
    }
    socket.onmessage = (ev) => {
      if (this.socket === socket) this.onFrame(ev.data)
    }
    socket.onerror = () => {
      /* the close event that follows drives reconnecting */
    }
    socket.onclose = (ev) => {
      if (this.socket !== socket) return
      this.socket = null
      this.onClosed(ev.code)
    }
  }

  private onClosed(code: number): void {
    if (this.stopped) return
    if (FATAL_CLOSE_CODES.has(code)) {
      this.dispatch({ type: 'connection', connection: 'error', closeCode: code })
      return
    }
    this.dispatch({ type: 'connection', connection: 'reconnecting', closeCode: code })
    const delay = this.backoffMs
    this.backoffMs = Math.min(this.backoffMs * 2, BACKOFF_MAX_MS)
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.connect()
    }, delay)
  }

  private onFrame(data: unknown): void {
    const parsed = parseIncoming(data)
    if (!parsed.ok) {
      this.options.onDiagnostic?.('invalid', parsed.error)
      return
    }
    const msg = parsed.msg
    const next = reduce(this.state, { type: 'incoming', msg })
    if (next === this.state) {
      this.options.onDiagnostic?.('dropped', `${msg.type} ${msg.id}`)
      return
    }
    this.commit(next)
    if (msg.type === 'hello_ack') {
      this.backoffMs = BACKOFF_MIN_MS
      this.send('mode_set', { mode: this.state.mode })
    }
  }

  private dispatch(action: Action): void {
    const next = reduce(this.state, action)
    if (next !== this.state) this.commit(next)
  }

  private commit(next: SessionState): void {
    this.state = next
    for (const l of this.listeners) l(next)
  }
}
