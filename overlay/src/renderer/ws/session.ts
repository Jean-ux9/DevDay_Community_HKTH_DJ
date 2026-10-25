// The overlay's view of the agent conversation, as a pure reducer (spec §4.4, client side).
// Everything the UI needs to render comes from here; nothing in the UI mutates it directly.
import type {
  AgentToOverlay,
  ChoiceOption,
  PayloadConfirmRequest,
  PayloadHelloAck,
  Permissions,
  Plan,
  Profile,
  Settings
} from './protocol.gen'

export type Mode = 'auto' | 'type'
export type Connection = 'connecting' | 'open' | 'reconnecting' | 'error'
export type TaskState = 'running' | 'waiting_user' | 'done' | 'failed' | 'stopped'

export interface TaskView {
  taskId: string
  state: TaskState
  step: number
  maxSteps: number
  message: string
}

/** The one selectable list: Auto suggestions, typed-intent plans or recovery cards (§4.4 "Lists"). */
export interface ListView {
  listId: string
  source: 'suggestions' | 'plans' | 'recovery'
  items: Plan[]
  app?: string
  windowKey?: string
  cached?: boolean
}

export interface ChoiceView {
  /** Id of the choice_request message: our response's `re`. */
  requestId: string
  taskId: string
  question: string
  options: ChoiceOption[]
}

export interface ConfirmView extends Omit<PayloadConfirmRequest, 'task_id'> {
  requestId: string
  taskId: string
}

export interface ResultView {
  taskId: string
  ok: boolean
  summary: string
  hasRecovery: boolean
}

export interface ErrorView {
  code: string
  message: string
  re: string | null
}

export interface SessionState {
  suggestPending: boolean
  suggestRequest: string | null
  stopping: boolean
  connection: Connection
  /** WebSocket close code of the last close (4401 auth, 4400 version). */
  closeCode: number | null
  /** True once hello_ack arrived on the current connection. */
  ready: boolean
  /** The last mode the user chose; it survives reconnects and is re-sent after every hello_ack. */
  mode: Mode
  demoMode: boolean
  profile: Profile | null
  settings: Settings | null
  /** Accessibility / Screen Recording as the agent reports them (camera is Electron's own). */
  agentPermissions: Permissions | null
  list: ListView | null
  /** Sentence cards from the last decode_result. */
  sentences: string[] | null
  task: TaskView | null
  choice: ChoiceView | null
  confirm: ConfirmView | null
  result: ResultView | null
  /** id of our plan_select awaiting its first task_status; that reply starts the task (§4.4). */
  pendingSelect: string | null
  lastError: ErrorView | null
  /** Bumped by stale_list / unknown_plan / task_busy so the dock re-syncs instead of crashing. */
  refreshTick: number
}

export const initialSession = (mode: Mode = 'auto'): SessionState => ({
  suggestPending: false,
  suggestRequest: null,
  stopping: false,
  connection: 'connecting',
  closeCode: null,
  ready: false,
  mode,
  demoMode: false,
  profile: null,
  settings: null,
  agentPermissions: null,
  list: null,
  sentences: null,
  task: null,
  choice: null,
  confirm: null,
  result: null,
  pendingSelect: null,
  lastError: null,
  refreshTick: 0
})

export type Action =
  | { type: 'incoming'; msg: AgentToOverlay }
  | { type: 'connection'; connection: Connection; closeCode?: number | null }
  | { type: 'mode'; mode: Mode }
  | { type: 'pending_select'; id: string }
  | { type: 'suggest'; id: string }
  /** The auto_refresh `id` got neither suggestions nor an error in time. */
  | { type: 'suggest_timeout'; id: string; message: string }
  | { type: 'stopping' }
  | { type: 'answered'; kind: 'choice' | 'confirm' }
  /** Back to the idle dock without telling the agent ("Something else", recovery:cancel, dismissing a result). */
  | { type: 'local_reset' }

const TERMINAL: ReadonlySet<TaskState> = new Set(['done', 'failed', 'stopped'])

/** The Auto dock is showing: suggestions are only useful (and only accepted) then (§4.4). */
export const autoDockShowing = (s: SessionState): boolean =>
  s.mode === 'auto' && s.task === null && s.confirm === null && s.choice === null && s.result === null

/** Only the most recent list is selectable (§4.4 "Lists"). */
export const isSelectable = (s: SessionState, listId: string, planId: string): boolean =>
  s.list !== null && s.list.listId === listId && s.list.items.some((p) => p.id === planId)

/** Why an incoming message must be ignored, or null to accept it (§4.4 task filtering). */
export function dropReason(s: SessionState, msg: AgentToOverlay): string | null {
  switch (msg.type) {
    case 'task_status': {
      const p = msg.payload
      if (s.task) {
        if (p.task_id !== s.task.taskId) return 'dead_task'
        return TERMINAL.has(s.task.state) ? 'dead_task' : null // only task_result may follow a terminal status
      }
      return p.state === 'running' && msg.re !== null && msg.re === s.pendingSelect ? null : 'dead_task'
    }
    case 'choice_request':
    case 'confirm_request':
    case 'task_result': {
      const p = msg.payload
      if (!s.task || p.task_id !== s.task.taskId) return 'dead_task'
      if (msg.type !== 'task_result' && (TERMINAL.has(s.task.state) || s.stopping)) return 'dead_task'
      return null
    }
    case 'suggestions':
      return autoDockShowing(s) ? null : 'not_auto_dock'
    default:
      return null
  }
}

/** Everything a fresh hello_ack wipes: the agent has no memory of this overlay's old tasks or lists. */
const idle = (s: SessionState): SessionState => ({
  ...s,
  list: null,
  sentences: null,
  task: null,
  choice: null,
  confirm: null,
  result: null,
  pendingSelect: null,
  suggestPending: false,
  suggestRequest: null,
  stopping: false,
  lastError: null
})

function incoming(s: SessionState, msg: AgentToOverlay): SessionState {
  if (dropReason(s, msg)) return s
  switch (msg.type) {
    case 'hello_ack': {
      const p: PayloadHelloAck = msg.payload
      return {
        ...idle(s),
        connection: 'open',
        closeCode: null,
        ready: true,
        demoMode: p.demo_mode,
        profile: p.profile,
        settings: p.settings,
        agentPermissions: { ...p.permissions }
      }
    }
    case 'permissions_status':
      return { ...s, agentPermissions: msg.payload }
    case 'suggestions': {
      const p = msg.payload
      return {
        ...s,
        suggestPending: false,
        suggestRequest: null,
        list: { listId: p.list_id, source: 'suggestions', items: p.items, app: p.app, windowKey: p.window_key, cached: p.cached }
      }
    }
    case 'decode_result':
      return { ...s, sentences: msg.payload.sentences }
    case 'plans':
      return { ...s, list: { listId: msg.payload.list_id, source: 'plans', items: msg.payload.items } }
    case 'task_status': {
      const p = msg.payload
      const view: TaskView = { taskId: p.task_id, state: p.state, step: p.step, maxSteps: p.max_steps, message: p.message }
      if (s.task === null) {
        // First reply to our plan_select: the dock collapses to the pill now, not when we sent it.
        return { ...s, task: view, pendingSelect: null, list: null, sentences: null, result: null, choice: null, confirm: null }
      }
      const ended = TERMINAL.has(p.state)
      return { ...s, task: view, choice: ended ? null : s.choice, confirm: ended ? null : s.confirm }
    }
    case 'choice_request': {
      const p = msg.payload
      return { ...s, confirm: null, choice: { requestId: msg.id, taskId: p.task_id, question: p.question, options: p.options } }
    }
    case 'confirm_request': {
      const { task_id, ...rest } = msg.payload
      return { ...s, choice: null, confirm: { ...rest, requestId: msg.id, taskId: task_id } }
    }
    case 'task_result': {
      const p = msg.payload
      const recovery = p.recovery && p.list_id ? p.recovery : null
      return {
        ...s,
        task: null,
        stopping: false,
        choice: null,
        confirm: null,
        result: { taskId: p.task_id, ok: p.ok, summary: p.summary, hasRecovery: recovery !== null },
        list: recovery && p.list_id ? { listId: p.list_id, source: 'recovery', items: recovery } : null
      }
    }
    case 'profile_result':
      return { ...s, profile: msg.payload.profile }
    case 'settings_result':
      return { ...s, settings: msg.payload.settings }
    case 'error': {
      const p = msg.payload
      const refresh = p.code === 'stale_list' || p.code === 'unknown_plan' || p.code === 'task_busy'
      return {
        ...s,
        suggestPending: s.suggestRequest === msg.re ? false : s.suggestPending,
        suggestRequest: s.suggestRequest === msg.re ? null : s.suggestRequest,
        lastError: { code: p.code, message: p.message, re: msg.re },
        pendingSelect: msg.re !== null && msg.re === s.pendingSelect ? null : s.pendingSelect,
        refreshTick: refresh ? s.refreshTick + 1 : s.refreshTick
      }
    }
  }
}

export function reduce(s: SessionState, action: Action): SessionState {
  switch (action.type) {
    case 'incoming':
      return incoming(s, action.msg)
    case 'connection':
      return { ...s, connection: action.connection, closeCode: action.closeCode ?? null, ready: action.connection === 'open' ? s.ready : false,
        ...(action.connection !== 'open' ? { suggestPending: false, suggestRequest: null, choice: null, confirm: null } : {}),
        // No reconnect will follow (the agent is gone or refused us): its task ended with the connection (§4.4).
        ...(action.connection === 'error' ? { task: null, pendingSelect: null, stopping: false } : {}) }
    case 'mode':
      return { ...s, mode: action.mode, suggestPending: false, suggestRequest: null }
    case 'suggest':
      return { ...s, suggestPending: true, suggestRequest: action.id }
    case 'suggest_timeout':
      return s.suggestRequest === action.id
        ? { ...s, suggestPending: false, suggestRequest: null, lastError: { code: 'suggest_timeout', message: action.message, re: action.id } }
        : s
    case 'stopping':
      return { ...s, stopping: true, choice: null, confirm: null }
    case 'pending_select':
      // A plan_select only goes out with no task, so a "stopping" left by an idle STOP is stale;
      // kept, it would drop this task's choice/confirm requests as dead.
      return { ...s, pendingSelect: action.id, stopping: false }
    case 'answered':
      return action.kind === 'choice' ? { ...s, choice: null } : { ...s, confirm: null }
    case 'local_reset':
      return { ...idle(s), lastError: null }
  }
}
