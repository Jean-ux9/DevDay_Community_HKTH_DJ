// Permissions checklist (spec §11): shown on first launch and whenever a permission goes missing.
// The platform re-checks every 2 s; this screen disappears by itself once every row is allowed.
import { useEffect, useRef, useState, type JSX } from 'react'
import { agent, useGaze, useSession } from '../platform'
import { Card } from '../dock/Card'
import { permissionRows, type Pane } from './permissions'

/** After this long still red, macOS usually wants the terminal app restarted (spec §11). */
export const RESTART_HINT_MS = 10_000

export function Onboarding(): JSX.Element | null {
  const s = useSession()
  const gaze = useGaze()
  const rows = permissionRows(s, gaze.source)
  const [opened, setOpened] = useState<Partial<Record<Pane, number>>>({})
  const [now, setNow] = useState(() => Date.now())
  const askedCamera = useRef(false)

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  // "Reaching the Camera row": ask for the camera once the agent's two permissions are allowed.
  const cameraRow = rows?.find(row => row.pane === 'camera')
  const agentReady = rows?.every(row => row.pane === 'camera' || row.ok) ?? false
  useEffect(() => {
    if (agentReady && cameraRow && !cameraRow.ok && s.permissions?.camera === 'not-determined' && !askedCamera.current) {
      askedCamera.current = true
      agent.openSettingsPane('camera')
    }
  }, [agentReady, cameraRow?.ok, s.permissions?.camera])

  if (!rows) return null
  const open = (pane: Pane) => {
    setOpened(o => ({ ...o, [pane]: Date.now() }))
    agent.openSettingsPane(pane)
  }

  return (
    <section className="panel-screen onboarding" aria-labelledby="onboarding-title">
      <h1 id="onboarding-title" className="screen-title">Before we start</h1>
      <p className="screen-lead">Gaze Copilot needs these permissions. A helper can click the buttons with the mouse.</p>
      <ul className="perm-list">
        {rows.map(row => {
          const since = opened[row.pane]
          const stuck = !row.ok && since !== undefined && now - since >= RESTART_HINT_MS
          return (
            <li key={row.pane} className={`perm-row${row.ok ? ' is-ok' : ''}`}>
              <span className="perm-dot" aria-hidden="true" />
              <span className="perm-text">
                <span className="perm-label">{row.label}</span>
                <span className="perm-why">{row.why}</span>
                {stuck && <span className="perm-hint">Still off? Quit and reopen the terminal app, then start again.</span>}
              </span>
              <span className="perm-state">{row.state}</span>
              {!row.ok && (
                <Card id={`perm-open-${row.pane}`} label="Open Settings" className="perm-open" clickable
                  onSelect={() => open(row.pane)} />
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
