// Full-screen, opaque confirmation before anything that sends, buys, deletes, submits or posts
// (spec §6.2, §9). CONFIRM is bottom-left and CANCEL top-right, so a drifting gaze can't confirm.
import { useEffect, useState, type CSSProperties, type JSX } from 'react'
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

/** "To: Sam" → "To". Only a short leading word or two counts, so a colon inside a message body doesn't. */
export const detailLabel = (line: string): string | null => /^([A-Za-z][A-Za-z ]{0,23}):(?=\s|$)/.exec(line)?.[1] ?? null

/** Long messages get smaller type so the whole recipient and text fit above CONFIRM (no gaze scrolling). */
const detailSize = (details: string[]): number | undefined => {
  const chars = details.reduce((n, line) => n + line.length, 0)
  return chars > 600 ? 20 : chars > 240 ? 26 : undefined
}

// The body ends above CONFIRM (bottom 64 + height 220) so a long message never runs under it;
// anything still too long scrolls by mouse or keyboard for a caregiver.
const BODY_STYLE: CSSProperties = { bottom: 316, overflowY: 'auto' }

/**
 * `onAnswer` hears every answer the screen gives (CONFIRM, CANCEL or the timeout) and whether it was
 * actually sent, so the result screen knows the user approved this task's action.
 */
export function ConfirmScreen({ confirm, onAnswer }: {
  confirm: Confirm
  onAnswer?: (confirmed: boolean, sent: boolean) => void
}): JSX.Element {
  const [left, setLeft] = useState(CONFIRM_TIMEOUT_MS / 1000)
  const answer = (confirmed: boolean) => {
    const sent = agent.respondConfirm(confirmed)
    onAnswer?.(confirmed, sent)
  }

  useEffect(() => {
    const started = Date.now()
    setLeft(CONFIRM_TIMEOUT_MS / 1000)
    const cancel = setTimeout(() => answer(false), CONFIRM_TIMEOUT_MS)
    const tick = setInterval(() => setLeft(Math.max(0, Math.ceil((CONFIRM_TIMEOUT_MS - (Date.now() - started)) / 1000))), 1000)
    return () => { clearTimeout(cancel); clearInterval(tick) }
  }, [confirm.requestId])

  const verb = VERBS[confirm.action]
  const size = detailSize(confirm.details)
  return (
    <div className={`confirm-screen action-${confirm.action}`} role="alertdialog"
      aria-labelledby="confirm-title" aria-describedby={confirm.details.length > 0 ? 'confirm-details' : undefined}>
      <div className="confirm-body" style={BODY_STYLE} tabIndex={0}>
        <div className="confirm-tags">
          <span className="confirm-tag"><ShieldIcon />Check before I {verb.toLowerCase()}</span>
          {confirm.demo_noop && <span className="demo-badge">Demo: nothing is bought</span>}
        </div>
        <h1 id="confirm-title" className="confirm-title">{confirm.title}</h1>
        {confirm.details.length > 0 && (
          // Each line exactly as the agent sent it (line breaks kept); only the label is emphasised.
          <ul id="confirm-details" className="confirm-details">
            {confirm.details.map((line, i) => {
              const label = detailLabel(line)
              return (
                <li key={i} style={{ whiteSpace: 'pre-wrap', ...(size ? { fontSize: size } : {}) }}>
                  {label === null ? line : <><strong className="confirm-detail-label">{label}:</strong>{line.slice(label.length + 1)}</>}
                </li>
              )
            })}
          </ul>
        )}
        <p className="confirm-source">{SOURCES[confirm.source]}</p>
      </div>

      {/* variant "confirm": the platform uses max(1500, 1.5 × dwellMs) for this target (§5.2). */}
      <DwellTarget id={`confirm-yes-${confirm.requestId}`} variant="confirm"
        onSelect={() => answer(true)} className="target confirm-yes">
        <span className="confirm-btn-label"><CheckIcon />{verb}</span>
        <span className="confirm-btn-sub">Look here to confirm</span>
      </DwellTarget>

      <DwellTarget id={`confirm-no-${confirm.requestId}`} variant="card"
        onSelect={() => answer(false)} className="target confirm-no">
        <span className="confirm-btn-label"><CloseIcon />Cancel</span>
        <span className="confirm-btn-sub">Don’t {verb.toLowerCase()}</span>
      </DwellTarget>

      <p className="confirm-timeout">Cancels by itself in {left} s</p>
    </div>
  )
}
