// The one big selectable card used by every dock list (suggestions, plans, choices, recovery).
import type { JSX, ReactNode } from 'react'
import { DwellTarget, type Plan } from '../platform'
import { AlertIcon, ArrowRightIcon, CloseIcon, EyeIcon, RetryIcon, ShieldIcon } from './icons'

export interface CardProps {
  id: string
  label: string
  detail?: string
  /** A third line, e.g. "Asks before sending". */
  note?: string
  icon?: ReactNode
  disabled?: boolean
  className?: string
  /** Also selectable by a real mouse click, for a caregiver (spec §6.1, §11). */
  clickable?: boolean
  /** Overrides the default dwell, e.g. a slower dwell for rarely used targets. */
  dwellMs?: number
  onSelect: () => void
}

export function Card({ id, label, detail, note, icon, disabled, className, clickable, dwellMs, onSelect }: CardProps): JSX.Element {
  return (
    <DwellTarget id={id} variant="card" disabled={disabled} dwellMs={dwellMs} onSelect={onSelect}
      className={['target', 'card', className].filter(Boolean).join(' ')}>
      {clickable && <CaregiverButton label={label} disabled={disabled} onClick={onSelect} />}
      {icon && <span className="card-icon">{icon}</span>}
      <span className="card-label">{label}</span>
      {detail && <span className="card-detail">{detail}</span>}
      {note && <span className="card-note"><ShieldIcon />{note}</span>}
    </DwellTarget>
  )
}

const RECOVERY_ICONS: Record<string, ReactNode> = {
  'recovery:retry': <RetryIcon />,
  'recovery:show_screen': <EyeIcon />,
  'recovery:cancel': <CloseIcon />
}

/** A `Plan` as a card. `risky` is only a hint; the real gate is the confirm screen (§9). */
export function PlanCard(props: { id: string; plan: Plan; disabled?: boolean; onSelect: () => void }): JSX.Element {
  const { plan } = props
  const icon = plan.kind === 'recovery' ? RECOVERY_ICONS[plan.id] ?? <AlertIcon />
    : plan.kind === 'other' ? <ArrowRightIcon /> : undefined
  return (
    <Card id={props.id} label={plan.label} detail={plan.detail} icon={icon} disabled={props.disabled}
      note={plan.risky ? 'Asks you first' : undefined}
      className={`plan-card kind-${plan.kind}`} onSelect={props.onSelect} />
  )
}

/**
 * A transparent button over a target. A real mouse hovering it turns click-through off (platform
 * README), so a caregiver can click; gaze still selects through the surrounding <DwellTarget>.
 */
export function CaregiverButton(props: { label: string; disabled?: boolean; onClick: () => void }): JSX.Element {
  return <button type="button" className="caregiver-hit" data-caregiver-clickable="" aria-label={props.label}
    disabled={props.disabled} onClick={props.onClick} />
}

/** Non-selectable text shown in a card slot (a hint, a summary, "Thinking…"). */
export function InfoPanel({ children, className }: { children: ReactNode; className?: string }): JSX.Element {
  return <div className={['info-panel', className].filter(Boolean).join(' ')}>{children}</div>
}
