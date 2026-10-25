// Which permissions block the overlay right now (spec §11).
import type { GazeState, SessionState } from '../platform'

export type Pane = 'accessibility' | 'screen_recording' | 'camera'

export interface PermissionRow {
  pane: Pane
  label: string
  why: string
  ok: boolean
  /** Short state in words, never colour alone. */
  state: string
}

/**
 * Accessibility and Screen Recording are always needed by the agent. The camera is needed only for
 * eye tracking: with mouse = gaze (dev and rescue mode) it is not, and the browser reports "unknown".
 */
export function permissionRows(s: SessionState, source: GazeState['source']): PermissionRow[] | null {
  const p = s.permissions
  if (!p) return null
  const cameraNeeded = source !== 'mouse'
  const camera = p.camera
  return [
    { pane: 'accessibility', label: 'Accessibility', why: 'Lets the agent press buttons and type for you',
      ok: p.accessibility, state: p.accessibility ? 'Allowed' : 'Not allowed' },
    { pane: 'screen_recording', label: 'Screen Recording', why: 'Lets the agent read the window you are using',
      ok: p.screen_recording, state: p.screen_recording ? 'Allowed' : 'Not allowed' },
    { pane: 'camera', label: 'Camera', why: cameraNeeded ? 'Follows your head or eyes' : 'Not needed while the mouse is the gaze',
      // "unknown" means no OS answer (e.g. a plain browser); the platform lets calibration try then.
      ok: camera === 'granted' || camera === 'unknown' || !cameraNeeded,
      state: camera === 'granted' ? 'Allowed' : camera === 'denied' || camera === 'restricted' ? 'Not allowed'
        : camera === 'not-determined' ? 'Not asked yet' : cameraNeeded ? 'Unknown' : 'Not needed' }
  ]
}

export const missingPermissions = (s: SessionState, source: GazeState['source']): Pane[] =>
  (permissionRows(s, source) ?? []).filter(row => !row.ok).map(row => row.pane)
