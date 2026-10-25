// STOP: fixed top-right, 160×160, red glass, 400 ms dwell, never covered (spec §6.2, §9.5).
import type { JSX } from 'react'
import { DwellTarget, agent, useSession } from '../platform'

/**
 * Always armed. It always sends stop{reason:"gaze"} (a no-op for the agent when idle); with no task
 * running it also closes whatever is open (settings, calibration, sentence or plan cards).
 */
export function StopTarget({ onIdle }: { onIdle?: () => void }): JSX.Element {
  const s = useSession()
  const running = !!s.task || !!s.pendingSelect
  const stopping = running && s.stopping
  return (
    <DwellTarget id="stop" variant="stop" disabled={stopping} clickable
      onSelect={() => { agent.stop('gaze'); if (!running) onIdle?.() }}
      className={`target stop-target${running ? ' is-running' : ''}`}>
      <span className="stop-square" aria-hidden="true" />
      <span className="stop-label">STOP</span>
      <span className="stop-sub">{stopping ? 'Stopping…' : running ? 'Look here' : 'Main menu'}</span>
    </DwellTarget>
  )
}
