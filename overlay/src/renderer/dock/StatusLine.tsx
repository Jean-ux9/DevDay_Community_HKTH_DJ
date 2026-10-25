// The status line above the dock, and the pill that replaces the dock while a task runs (§6.2).
import type { JSX } from 'react'
import type { SessionState } from '../platform'
import { Spinner } from './icons'
import type { Status } from './status'

export function StatusLine({ status }: { status: Status }): JSX.Element {
  const busy = status.kind === 'thinking' || status.kind === 'acting' || status.kind === 'connecting'
  return (
    <div className={`status-line status-${status.kind}`} role="status">
      {busy ? <Spinner /> : <span className="status-dot" aria-hidden="true" />}
      <span>{status.text}</span>
    </div>
  )
}

export function StatusPill({ task, status }: { task: NonNullable<SessionState['task']>; status: Status }): JSX.Element {
  const progress = Math.min(1, task.step / Math.max(1, task.maxSteps))
  return (
    <div className={`status-pill status-${status.kind}`} role="status">
      <div className="pill-top">
        {status.kind === 'acting' ? <Spinner /> : <span className="status-dot" aria-hidden="true" />}
        {/* Keyed by text: each new step remounts and fades in (styles/glass.css). */}
        <span key={task.message || status.text} className="pill-message">{task.message || status.text}</span>
      </div>
      <div className="pill-bottom">
        <span className="pill-step">Step {task.step} of {task.maxSteps}</span>
        <span className="pill-bar" aria-hidden="true"><span style={{ transform: `scaleX(${progress})` }} /></span>
        {/* "Acting · step n" would repeat the step count; show only the other states. */}
        {!status.text.startsWith('Acting') && <span className="pill-state">{status.text}</span>}
      </div>
    </div>
  )
}
