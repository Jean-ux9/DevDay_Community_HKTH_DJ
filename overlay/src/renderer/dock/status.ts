// One line of plain words for what the copilot is doing right now (status line + pill).
import type { SessionState } from '../platform'

export type StatusKind = 'connecting' | 'connected' | 'thinking' | 'acting' | 'waiting' | 'error'

export interface Status {
  kind: StatusKind
  text: string
}

/** What the overlay itself is waiting for (the session has no pending flag for these). */
export type Awaiting = 'decode' | 'plans' | null

/** Errors that only make the dock re-sync; they are not worth showing the user (§4.4). */
const QUIET_ERRORS = new Set(['stale_list', 'unknown_plan', 'task_busy', 'no_task'])
export const isQuietError = (code: string): boolean => QUIET_ERRORS.has(code)

export function deriveStatus(s: SessionState, awaiting: Awaiting = null): Status {
  if (s.connection === 'error') {
    if (s.closeCode === 4401) return { kind: 'error', text: 'The agent refused the connection' }
    if (s.closeCode === 4400) return { kind: 'error', text: 'Agent version mismatch' }
    // Electron main: the agent process it started has exited (details in its terminal).
    if (s.closeCode === 4500) return { kind: 'error', text: 'The agent stopped' }
    return { kind: 'error', text: s.lastError?.message ?? 'Cannot reach the agent' }
  }
  if (s.connection === 'reconnecting') return { kind: 'connecting', text: 'Reconnecting…' }
  if (s.connection !== 'open' || !s.ready) return { kind: 'connecting', text: 'Connecting…' }
  if (s.task) {
    if (s.stopping) return { kind: 'acting', text: 'Stopping…' }
    if (s.confirm) return { kind: 'waiting', text: 'Waiting for you to confirm' }
    if (s.choice || s.task.state === 'waiting_user') return { kind: 'waiting', text: 'Waiting for you' }
    return { kind: 'acting', text: `Acting · step ${s.task.step} of ${s.task.maxSteps}` }
  }
  if (s.pendingSelect) return { kind: 'acting', text: 'Starting…' }
  if (s.suggestPending || awaiting) return { kind: 'thinking', text: 'Thinking…' }
  if (s.lastError && !isQuietError(s.lastError.code)) return { kind: 'error', text: s.lastError.message }
  return { kind: 'connected', text: 'Ready' }
}
