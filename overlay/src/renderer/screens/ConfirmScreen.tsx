// Full-screen, opaque confirmation before anything that sends, buys, deletes, submits or posts
// (spec §6.2, §9). CONFIRM is bottom-left and CANCEL top-right, so a drifting gaze can't confirm.
import { useEffect, useState, type JSX } from 'react'
import { DwellTarget, agent, type SessionState } from '../platform'
import { CheckIcon, CloseIcon, ShieldIcon } from '../dock/icons'

/** The overlay answers `false` on its own after this long (spec §4.4). */
export const CONFIRM_TIMEOUT_MS = 60_000

type Confirm = NonNullable<SessionState['confirm']>

const VERBS: Record<Confirm['action'], string> = {
  send: 'Send', buy: 'Buy', delete: 'Delete', submit: 'Submit', post: 'Post', other: 'Confirm'
}

const SOURCES: Record<Confirm['source'], string> = {
  rule: 'A safety rule stopped here before acting.',
  model: 'The assistant stopped here to check with you.',
  both: 'A safety rule and the assistant both stopped here.'
}

export function ConfirmScreen({ confirm }: { confirm: Confirm }): JSX.Element {
  const [left, setLeft] = useState(CONFIRM_TIMEOUT_MS / 1000)

  useEffect(() => {
    const started = Date.now()
    setLeft(CONFIRM_TIMEOUT_MS / 1000)
    const cancel = setTimeout(() => agent.respondConfirm(false), CONFIRM_TIMEOUT_MS)
    const tick = setInterval(() => setLeft(Math.max(0, Math.ceil((CONFIRM_TIMEOUT_MS - (Date.now() - started)) / 1000))), 1000)
    return () => { clearTimeout(cancel); clearInterval(tick) }
  }, [confirm.requestId])

  const verb = VERBS[confirm.action]
  return (
    <div className={`confirm-screen action-${confirm.action}`} role="alertdialog" aria-labelledby="confirm-title">
      <div className="confirm-body">
        <div className="confirm-tags">
          <span className="confirm-tag"><ShieldIcon />Check before I {verb.toLowerCase()}</span>
          {confirm.demo_noop && <span className="demo-badge">Demo: nothing is bought</span>}
        </div>
        <h1 id="confirm-title" className="confirm-title">{confirm.title}</h1>
        {confirm.details.length > 0 && (
          <ul className="confirm-details">
            {confirm.details.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
        )}
        <p className="confirm-source">{SOURCES[confirm.source]}</p>
      </div>

      {/* variant "confirm": the platform uses max(1500, 1.5 × dwellMs) for this target (§5.2). */}
      <DwellTarget id={`confirm-yes-${confirm.requestId}`} variant="confirm"
        onSelect={() => agent.respondConfirm(true)} className="target confirm-yes">
        <span className="confirm-btn-label"><CheckIcon />{verb}</span>
        <span className="confirm-btn-sub">Look here to confirm</span>
      </DwellTarget>

      <DwellTarget id={`confirm-no-${confirm.requestId}`} variant="card"
        onSelect={() => agent.respondConfirm(false)} className="target confirm-no">
        <span className="confirm-btn-label"><CloseIcon />Cancel</span>
        <span className="confirm-btn-sub">Don’t {verb.toLowerCase()}</span>
      </DwellTarget>

      <p className="confirm-timeout">Cancels by itself in {left} s</p>
    </div>
  )
}
