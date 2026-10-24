// STOP: fixed top-right, 160×160, red glass, 400 ms dwell, never covered (spec §6.2, §9.5).
import type { JSX } from 'react'
import { DwellTarget, agent, useSession } from '../platform'

/**
 * Always on screen so the user always knows where it is, but only armed while a task exists.
 * An idle stop is a no-op for the agent, yet it leaves the session in "stopping", which would
 * drop the next task's confirm request.
 */
export function StopTarget(): JSX.Element {
  const s = useSession()
  const armed = !!s.task && !s.stopping
  return (
    <DwellTarget id="stop" variant="stop" disabled={!armed} onSelect={() => agent.stop('gaze')}
      className={`target stop-target${armed ? ' is-armed' : ''}`}>
      <span className="stop-square" aria-hidden="true" />
      <span className="stop-label">STOP</span>
      <span className="stop-sub">{s.stopping ? 'Stopping…' : armed ? 'Look here' : 'Idle'}</span>
    </DwellTarget>
  )
}
