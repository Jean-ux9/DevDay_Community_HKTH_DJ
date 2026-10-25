// Back (the STOP target, spec §6.2, §9.5): in the top-right column under Hide and Settings, red,
// 400 ms dwell, never covered. At rest a
// red circle with a return arrow; while a task runs it stays a full square so stopping is instant.
import type { JSX } from 'react'
import { agent, useSession } from '../platform'
import { CornerTarget } from '../dock/CornerTarget'
import { ReturnIcon } from '../dock/icons'

/**
 * Always armed. It always sends stop{reason:"gaze"} (a no-op for the agent when idle); with no task
 * running it also closes whatever is open (settings, calibration, sentence or plan cards).
 */
export function StopTarget({ onIdle }: { onIdle?: () => void }): JSX.Element {
  const s = useSession()
  const running = !!s.task || !!s.pendingSelect
  const stopping = running && s.stopping
  return (
    <CornerTarget id="stop" variant="stop" disabled={stopping} clickable {...(running ? { startDelayMs: 0 } : {})}
      onSelect={() => { agent.stop('gaze'); if (!running) onIdle?.() }}
      className={`stop-target corner-back${running ? ' is-running' : ''}`}
      icon={<ReturnIcon />} label="Back" sub={stopping ? 'Stopping…' : running ? 'Stops the task' : undefined} />
  )
}
